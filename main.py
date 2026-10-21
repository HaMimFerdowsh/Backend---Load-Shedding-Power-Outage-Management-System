from datetime import datetime
from typing import Annotated, Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

import models
from models import Areas, LoadSheddingSchedules, Outages
from database import engine, SessionLocal
from router import admin, auth
from router.auth import get_current_user
from router.admin import paginate, apply_sort, CATEGORY, SCHEDULE_STATUS, OUTAGE_STATUS

app = FastAPI(title='Load Shedding & Power Outage Management System')


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


models.Base.metadata.create_all(bind=engine)
app.include_router(auth.router)
app.include_router(admin.router)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]


class OutageCreate(BaseModel):
    area_id: int
    title: str = Field(min_length=3, max_length=150)
    description: str = Field(min_length=10, max_length=1000)
    category: CATEGORY = 'other'


class OutageEdit(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=150)
    description: Optional[str] = Field(default=None, min_length=10, max_length=1000)
    category: Optional[CATEGORY] = None


# ---------------------------------------------------------------
# Areas (public, so the signup form can show an area dropdown)
# ---------------------------------------------------------------
@app.get('/areas/all')
def get_all_areas(
    db: db_dependency,
    search: Optional[str] = None,                        # name / ID
    zone: Optional[str] = None,
    district: Optional[str] = None,
    sort_by: str = Query('name', pattern='^(name|zone|district|created_at)$'),
    order: str = Query('asc', pattern='^(asc|desc)$'),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    query = db.query(Areas)

    if search:
        cond = [Areas.name.ilike(f'%{search}%')]
        if search.isdigit():
            cond.append(Areas.id == int(search))
        query = query.filter(or_(*cond))
    if zone:
        query = query.filter(Areas.zone == zone)
    if district:
        query = query.filter(Areas.district == district)

    return paginate(apply_sort(query, Areas, sort_by, order), page, page_size)


# ---------------------------------------------------------------
# Load shedding schedules (everyone logged in can view)
# ---------------------------------------------------------------
@app.get('/schedules')
def get_all_schedules(
    user: user_dependency,
    db: db_dependency,
    search: Optional[str] = None,                        # title / ID
    area_id: Optional[int] = None,
    status: Optional[SCHEDULE_STATUS] = None,
    from_date: Optional[datetime] = None,                # start_time range
    to_date: Optional[datetime] = None,
    sort_by: str = Query('start_time', pattern='^(start_time|end_time|title|status)$'),
    order: str = Query('desc', pattern='^(asc|desc)$'),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    S = LoadSheddingSchedules
    query = db.query(S)

    if search:
        cond = [S.title.ilike(f'%{search}%')]
        if search.isdigit():
            cond.append(S.id == int(search))
        query = query.filter(or_(*cond))
    if area_id:
        query = query.filter(S.area_id == area_id)
    if status:
        query = query.filter(S.status == status)
    if from_date:
        query = query.filter(S.start_time >= from_date)
    if to_date:
        query = query.filter(S.start_time <= to_date)

    return paginate(apply_sort(query, S, sort_by, order), page, page_size)


# ---------------------------------------------------------------
# Outages (user reports and manages own reports)
# ---------------------------------------------------------------
@app.post('/outages/report')
def report_outage(user: user_dependency, db: db_dependency, new_outage: OutageCreate):

    if db.query(Areas).filter(Areas.id == new_outage.area_id).first() is None:
        raise HTTPException(status_code=404, detail='Area Not Found')

    outage_model = Outages(
        **new_outage.model_dump(),
        reported_by=user.get('id'),
        status='reported',
    )

    db.add(outage_model)
    db.commit()

    return JSONResponse(status_code=201, content={'message': 'Outage reported successfully'})


@app.get('/outages/my')
def my_outages(
    user: user_dependency,
    db: db_dependency,
    search: Optional[str] = None,                        # title / ID
    status: Optional[OUTAGE_STATUS] = None,
    category: Optional[CATEGORY] = None,
    from_date: Optional[datetime] = None,                # created_at range
    to_date: Optional[datetime] = None,
    sort_by: str = Query('created_at', pattern='^(created_at|title|status)$'),
    order: str = Query('desc', pattern='^(asc|desc)$'),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    query = db.query(Outages).filter(Outages.reported_by == user.get('id'))

    if search:
        cond = [Outages.title.ilike(f'%{search}%')]
        if search.isdigit():
            cond.append(Outages.id == int(search))
        query = query.filter(or_(*cond))
    if status:
        query = query.filter(Outages.status == status)
    if category:
        query = query.filter(Outages.category == category)
    if from_date:
        query = query.filter(Outages.created_at >= from_date)
    if to_date:
        query = query.filter(Outages.created_at <= to_date)

    return paginate(apply_sort(query, Outages, sort_by, order), page, page_size)


@app.put('/outages/edit/{outage_id}')
def edit_outage(user: user_dependency, db: db_dependency, update_outage: OutageEdit, outage_id: int):

    outage = db.query(Outages).filter(
        Outages.id == outage_id, Outages.reported_by == user.get('id')
    ).first()
    if outage is None:
        raise HTTPException(status_code=404, detail='Outage is not Found')
    if outage.status != 'reported':
        raise HTTPException(status_code=400, detail='Only reports that are still "reported" can be edited')

    update_data = update_outage.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(outage, key, value)

    db.commit()

    return JSONResponse(status_code=200, content={'message': 'Outage report updated successfully'})


@app.delete('/outages/delete/{outage_id}')
def delete_my_outage(user: user_dependency, db: db_dependency, outage_id: int):

    outage = db.query(Outages).filter(
        Outages.id == outage_id, Outages.reported_by == user.get('id')
    ).first()
    if outage is None:
        raise HTTPException(status_code=404, detail='Outage is not Found')
    if outage.status != 'reported':
        raise HTTPException(status_code=400, detail='Only reports that are still "reported" can be deleted')

    db.delete(outage)
    db.commit()

    return JSONResponse(status_code=200, content={'message': 'Outage report deleted successfully'})