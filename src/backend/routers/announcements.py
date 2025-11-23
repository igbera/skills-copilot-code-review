"""
Announcements endpoints for the High School Management System API
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
from datetime import datetime
from bson import ObjectId

from ..database import announcements_collection, teachers_collection

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


def serialize_announcement(announcement: Dict[str, Any]) -> Dict[str, Any]:
    """Convert MongoDB announcement document to JSON-serializable format"""
    if "_id" in announcement and isinstance(announcement["_id"], ObjectId):
        announcement["id"] = str(announcement["_id"])
        del announcement["_id"]
    return announcement


@router.get("", response_model=List[Dict[str, Any]])
@router.get("/", response_model=List[Dict[str, Any]])
def get_announcements(active_only: bool = Query(False)) -> List[Dict[str, Any]]:
    """
    Get all announcements, optionally filtered to show only currently active ones
    
    - active_only: If true, only return announcements within their active date range
    """
    query = {}
    
    if active_only:
        now = datetime.utcnow()
        query = {
            "$and": [
                {"$or": [
                    {"start_date": {"$exists": False}},
                    {"start_date": {"$lte": now}}
                ]},
                {"expiration_date": {"$gte": now}}
            ]
        }
    
    announcements = []
    for announcement in announcements_collection.find(query).sort("created_at", -1):
        announcements.append(serialize_announcement(announcement))
    
    return announcements


@router.get("/{announcement_id}", response_model=Dict[str, Any])
def get_announcement(announcement_id: str) -> Dict[str, Any]:
    """Get a specific announcement by ID"""
    try:
        announcement = announcements_collection.find_one({"_id": ObjectId(announcement_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid announcement ID format")
    
    if not announcement:
        raise HTTPException(status_code=404, detail="Announcement not found")
    
    return serialize_announcement(announcement)


@router.post("", response_model=Dict[str, Any])
@router.post("/", response_model=Dict[str, Any])
def create_announcement(
    message: str,
    expiration_date: str,
    start_date: Optional[str] = None,
    teacher_username: str = Query(...)
) -> Dict[str, Any]:
    """
    Create a new announcement - requires teacher authentication
    
    - message: The announcement text
    - expiration_date: Required ISO 8601 datetime when announcement expires
    - start_date: Optional ISO 8601 datetime when announcement becomes active (defaults to now)
    - teacher_username: Username of the authenticated teacher
    """
    # Validate teacher authentication
    teacher = teachers_collection.find_one({"_id": teacher_username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")
    
    # Validate dates
    try:
        exp_date = datetime.fromisoformat(expiration_date.replace('Z', '+00:00'))
        if start_date:
            st_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            if st_date >= exp_date:
                raise HTTPException(
                    status_code=400,
                    detail="Start date must be before expiration date"
                )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO 8601 format")
    
    # Create announcement document
    announcement = {
        "message": message,
        "expiration_date": expiration_date,
        "created_by": teacher_username,
        "created_at": datetime.utcnow().isoformat()
    }
    
    if start_date:
        announcement["start_date"] = start_date
    
    # Insert into database
    result = announcements_collection.insert_one(announcement)
    announcement["id"] = str(result.inserted_id)
    
    return announcement


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(
    announcement_id: str,
    message: Optional[str] = None,
    expiration_date: Optional[str] = None,
    start_date: Optional[str] = None,
    teacher_username: str = Query(...)
) -> Dict[str, Any]:
    """
    Update an existing announcement - requires teacher authentication
    
    - announcement_id: ID of the announcement to update
    - message: Updated announcement text
    - expiration_date: Updated expiration date
    - start_date: Updated start date (use empty string to remove)
    - teacher_username: Username of the authenticated teacher
    """
    # Validate teacher authentication
    teacher = teachers_collection.find_one({"_id": teacher_username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")
    
    # Check announcement exists
    try:
        existing = announcements_collection.find_one({"_id": ObjectId(announcement_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid announcement ID format")
    
    if not existing:
        raise HTTPException(status_code=404, detail="Announcement not found")
    
    # Build update document
    update_fields = {}
    
    if message is not None:
        update_fields["message"] = message
    
    if expiration_date is not None:
        try:
            datetime.fromisoformat(expiration_date.replace('Z', '+00:00'))
            update_fields["expiration_date"] = expiration_date
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid expiration date format")
    
    if start_date is not None:
        if start_date == "":
            # Remove start_date field
            announcements_collection.update_one(
                {"_id": ObjectId(announcement_id)},
                {"$unset": {"start_date": ""}}
            )
        else:
            try:
                datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                update_fields["start_date"] = start_date
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start date format")
    
    # Validate date relationship if both are being set
    final_start = update_fields.get("start_date", existing.get("start_date"))
    final_exp = update_fields.get("expiration_date", existing.get("expiration_date"))
    
    if final_start and final_exp:
        try:
            st_date = datetime.fromisoformat(final_start.replace('Z', '+00:00'))
            exp_date = datetime.fromisoformat(final_exp.replace('Z', '+00:00'))
            if st_date >= exp_date:
                raise HTTPException(
                    status_code=400,
                    detail="Start date must be before expiration date"
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format in start_date or expiration_date")
    
    if update_fields:
        announcements_collection.update_one(
            {"_id": ObjectId(announcement_id)},
            {"$set": update_fields}
        )
    
    # Return updated announcement
    updated = announcements_collection.find_one({"_id": ObjectId(announcement_id)})
    return serialize_announcement(updated)


@router.delete("/{announcement_id}")
def delete_announcement(
    announcement_id: str,
    teacher_username: str = Query(...)
) -> Dict[str, str]:
    """
    Delete an announcement - requires teacher authentication
    
    - announcement_id: ID of the announcement to delete
    - teacher_username: Username of the authenticated teacher
    """
    # Validate teacher authentication
    teacher = teachers_collection.find_one({"_id": teacher_username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")
    
    # Delete the announcement
    try:
        result = announcements_collection.delete_one({"_id": ObjectId(announcement_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid announcement ID format")
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")
    
    return {"message": "Announcement deleted successfully"}
