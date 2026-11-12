from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.asynchronous.database import AsyncDatabase

from app.database import collections


async def create_indexes(database: AsyncDatabase) -> None:
    indexes = [
        (collections.USERS, [("email", ASCENDING)], {"unique": True, "name": "users_email_unique"}),
        (collections.CANDIDATE_PROFILES, [("user_id", ASCENDING)], {"unique": True, "name": "candidate_profiles_user_unique"}),
        (collections.RECRUITER_PROFILES, [("user_id", ASCENDING)], {"unique": True, "name": "recruiter_profiles_user_unique"}),
        (collections.COMPANIES, [("recruiter_id", ASCENDING)], {"unique": True, "name": "companies_recruiter_unique"}),
        (collections.APPLICATIONS, [("candidate_id", ASCENDING), ("job_id", ASCENDING)], {"unique": True, "name": "applications_candidate_job_unique"}),
        (collections.SAVED_JOBS, [("candidate_id", ASCENDING), ("job_id", ASCENDING)], {"unique": True, "name": "saved_jobs_candidate_job_unique"}),
        (collections.JOBS, [("status", ASCENDING), ("created_at", DESCENDING)], {"name": "jobs_status_created"}),
        (collections.JOBS, [("title", TEXT), ("description", TEXT), ("required_skills", TEXT)], {"name": "jobs_search_text"}),
        (collections.RESUMES, [("candidate_id", ASCENDING), ("created_at", DESCENDING)], {"name": "resumes_candidate_created"}),
        (collections.APPLICATIONS, [("job_id", ASCENDING), ("status", ASCENDING)], {"name": "applications_job_status"}),
        (collections.NOTIFICATIONS, [("user_id", ASCENDING), ("created_at", DESCENDING)], {"name": "notifications_user_created"}),
        (collections.INTERVIEWS, [("recruiter_id", ASCENDING), ("status", ASCENDING), ("scheduled_at", ASCENDING)], {"name": "interviews_recruiter_status_date"}),
        (collections.INTERVIEWS, [("candidate_id", ASCENDING), ("scheduled_at", ASCENDING)], {"name": "interviews_candidate_date"}),
        (collections.ASSESSMENTS, [("application_id", ASCENDING)], {"unique": True, "name": "assessments_application_unique"}),
        (collections.ASSESSMENTS, [("candidate_id", ASCENDING), ("created_at", DESCENDING)], {"name": "assessments_candidate_created"}),
        (collections.ASSESSMENTS, [("recruiter_id", ASCENDING), ("created_at", DESCENDING)], {"name": "assessments_recruiter_created"}),
        (collections.ASSESSMENT_QUESTIONS, [("category", ASCENDING), ("difficulty", ASCENDING)], {"name": "assessment_questions_category_difficulty"}),
        (collections.ASSESSMENT_QUESTIONS, [("question_key", ASCENDING)], {"unique": True, "name": "assessment_questions_key_unique"}),
    ]
    for collection_name, keys, options in indexes:
        await database[collection_name].create_index(keys, **options)
