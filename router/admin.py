from datetime import datetime
from typing import Optional, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import or_

from models import Users, Areas, LoadSheddingSchedules, Outages
# If your auth.py is in the project root, change this to:  from auth import ...
from router.auth import db_dependency, admin_dependency

router = APIRouter()

CATEGORY = Literal['transformer_fault', 'line_break', 'storm', 'overload', 'other']
SCHEDULE_STATUS = Literal['scheduled', 'ongoing', 'completed', 'cancelled']
OUTAGE_STATUS = Literal['reported', 'investigating', 'resolved', 'rejected']


# ---------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------
class AreaCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    zone: str = Field(min_length=2, max_length=50)
    district: str = Field(min_length=2, max_length=50)


class AreaUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    zone: Optional[str] = Field(default=None, min_length=2, max_length=50)
    district: Optional[str] = Field(default=None, min_length=2, max_length=50)


class ScheduleCreate(BaseModel):
    area_id: int
    title: str = Field(min_length=3, max_length=150)
    reason: str = Field(min_length=3, max_length=200)
    start_time: datetime
    end_time: datetime

    @model_validator(mode='after')
    def end_after_start(self):
        if self.end_time <= self.start_time:
            raise ValueError('end_time must be after start_time')
        return self


class ScheduleUpdate(BaseModel):
    area_id: Optional[int] = None
    title: Optional[str] = Field(default=None, min_length=3, max_length=150)
    reason: Optional[str] = Field(default=None, min_length=3, max_length=200)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: Optional[SCHEDULE_STATUS] = None


class OutageStatusUpdate(BaseModel):
    status: OUTAGE_STATUS


# ---------------------------------------------------------------
# Helpers (main.py imports these too)
# ---------------------------------------------------------------
def to_dict(obj):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def paginate(query, page: int, page_size: int):
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        'items': [to_dict(i) for i in items],
        'total': total,
        'page': page,
        'page_size': page_size,
    }


def apply_sort(query, model, sort_by: str, order: str):
    column = getattr(model, sort_by)
    return query.order_by(column.asc() if order == 'asc' else column.desc())


# ---------------------------------------------------------------
# Areas
# ---------------------------------------------------------------
@router.post('/admin/create_area')
def create_area(admin: admin_dependency, db: db_dependency, new_area: AreaCreate):

    if db.query(Areas).filter(Areas.name == new_area.name).first():
        raise HTTPException(status_code=400, detail='Area name already exists')

    db.add(Areas(**new_area.model_dump()))
    db.commit()

    return JSONResponse(status_code=201, content={'message': 'Area added successfully'})


@router.put('/admin/update_area/{area_id}')
def update_area(admin: admin_dependency, db: db_dependency, update_area: AreaUpdate, area_id: int):

    area = db.query(Areas).filter(Areas.id == area_id).first()
    if area is None:
        raise HTTPException(status_code=404, detail='Area Not Found')

    update_data = update_area.model_dump(exclude_unset=True)

    if 'name' in update_data and update_data['name'] != area.name:
        if db.query(Areas).filter(Areas.name == update_data['name']).first():
            raise HTTPException(status_code=400, detail='Area name already exists')

    for key, value in update_data.items():
        setattr(area, key, value)

    db.commit()
    return JSONResponse(status_code=200, content={'message': 'Area updated successfully'})


@router.delete('/admin/delete_area/{area_id}')
def delete_area(admin: admin_dependency, db: db_dependency, area_id: int):

    area = db.query(Areas).filter(Areas.id == area_id).first()
    if area is None:
        raise HTTPException(status_code=404, detail='Area Not Found')

    in_use = (
        db.query(Users).filter(Users.area_id == area_id).first()
        or db.query(LoadSheddingSchedules).filter(LoadSheddingSchedules.area_id == area_id).first()
        or db.query(Outages).filter(Outages.area_id == area_id).first()
    )
    if in_use:
        raise HTTPException(status_code=400, detail='Area is in use by users, schedules or outages')

    db.delete(area)
    db.commit()
    return JSONResponse(status_code=200, content={'message': 'Area deleted successfully'})


# ---------------------------------------------------------------
# Load shedding schedules
# ---------------------------------------------------------------
@router.post('/admin/create_schedule')
def create_schedule(admin: admin_dependency, db: db_dependency, new_schedule: ScheduleCreate):

    if db.query(Areas).filter(Areas.id == new_schedule.area_id).first() is None:
        raise HTTPException(status_code=404, detail='Area Not Found')

    db.add(LoadSheddingSchedules(**new_schedule.model_dump(), status='scheduled'))
    db.commit()

    return JSONResponse(status_code=201, content={'message': 'Schedule created successfully'})


@router.put('/admin/update_schedule/{schedule_id}')
def update_schedule(admin: admin_dependency, db: db_dependency,
                    update_schedule: ScheduleUpdate, schedule_id: int):

    schedule = db.query(LoadSheddingSchedules).filter(LoadSheddingSchedules.id == schedule_id).first()
    if schedule is None:
        raise HTTPException(status_code=404, detail='Schedule Not Found')

    update_data = update_schedule.model_dump(exclude_unset=True)

    if update_data.get('area_id') and db.query(Areas).filter(Areas.id == update_data['area_id']).first() is None:
        raise HTTPException(status_code=404, detail='Area Not Found')

    start = update_data.get('start_time', schedule.start_time)
    end = update_data.get('end_time', schedule.end_time)
    if end <= start:
        raise HTTPException(status_code=422, detail='end_time must be after start_time')

    for key, value in update_data.items():
        setattr(schedule, key, value)

    db.commit()
    return JSONResponse(status_code=200, content={'message': 'Schedule updated successfully'})


@router.delete('/admin/delete_schedule/{schedule_id}')
def delete_schedule(admin: admin_dependency, db: db_dependency, schedule_id: int):

    schedule = db.query(LoadSheddingSchedules).filter(LoadSheddingSchedules.id == schedule_id).first()
    if schedule is None:
        raise HTTPException(status_code=404, detail='Schedule Not Found')

    db.delete(schedule)
    db.commit()
    return JSONResponse(status_code=200, content={'message': 'Schedule deleted successfully'})


# ---------------------------------------------------------------
# Outages (reported by users, reviewed by admin)
# ---------------------------------------------------------------
@router.get('/admin/outages')
def list_all_outages(
    admin: admin_dependency,
    db: db_dependency,
    search: Optional[str] = None,                        # title / ID
    status: Optional[OUTAGE_STATUS] = None,
    category: Optional[CATEGORY] = None,
    area_id: Optional[int] = None,
    from_date: Optional[datetime] = None,                # created_at range
    to_date: Optional[datetime] = None,
    sort_by: str = Query('created_at', pattern='^(created_at|title|status)$'),
    order: str = Query('desc', pattern='^(asc|desc)$'),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    query = db.query(Outages)

    if search:
        cond = [Outages.title.ilike(f'%{search}%')]
        if search.isdigit():
            cond.append(Outages.id == int(search))
        query = query.filter(or_(*cond))
    if status:
        query = query.filter(Outages.status == status)
    if category:
        query = query.filter(Outages.category == category)
    if area_id:
        query = query.filter(Outages.area_id == area_id)
    if from_date:
        query = query.filter(Outages.created_at >= from_date)
    if to_date:
        query = query.filter(Outages.created_at <= to_date)

    return paginate(apply_sort(query, Outages, sort_by, order), page, page_size)


@router.put('/admin/update_outage/{outage_id}')
def update_outage_status(admin: admin_dependency, db: db_dependency,
                         update_outage: OutageStatusUpdate, outage_id: int):

    outage = db.query(Outages).filter(Outages.id == outage_id).first()
    if outage is None:
        raise HTTPException(status_code=404, detail='Outage Not Found')

    outage.status = update_outage.status
    db.commit()
    return JSONResponse(status_code=200, content={'message': 'Outage status updated successfully'})