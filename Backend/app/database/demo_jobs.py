import asyncio
from datetime import datetime, timedelta, timezone

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.config import settings
from app.database.collections import JOBS

DEMO_ROLES = [
    {
        "title": "Frontend Developer",
        "company_name": "Northstar Labs (Demo)",
        "location": "Remote",
        "job_type": "Full-time",
        "description": "Build accessible, responsive product experiences with a collaborative design and engineering team.",
        "responsibilities": ["Build reusable React interfaces", "Improve accessibility and page performance"],
        "requirements": ["Experience with modern JavaScript", "Comfortable working with REST APIs"],
        "required_skills": ["React", "JavaScript", "CSS", "Accessibility"],
        "experience_min": 1,
        "experience_max": 4,
        "salary_min": 65000,
        "salary_max": 90000,
    },
    {
        "title": "Python Backend Developer",
        "company_name": "Cedar Peak Software (Demo)",
        "location": "Austin, TX",
        "job_type": "Full-time",
        "description": "Develop reliable APIs and data services for a growing career technology product.",
        "responsibilities": ["Design and maintain API endpoints", "Write tests and improve service reliability"],
        "requirements": ["Experience building Python services", "Knowledge of databases and API design"],
        "required_skills": ["Python", "FastAPI", "MongoDB", "REST API"],
        "experience_min": 2,
        "experience_max": 5,
        "salary_min": 80000,
        "salary_max": 115000,
    },
    {
        "title": "Product Data Analyst",
        "company_name": "Brightfield Analytics (Demo)",
        "location": "New York, NY",
        "job_type": "Full-time",
        "description": "Turn product usage and customer feedback into clear recommendations for product teams.",
        "responsibilities": ["Analyze product and business metrics", "Present findings to cross-functional partners"],
        "requirements": ["Strong analytical and communication skills", "Experience querying structured data"],
        "required_skills": ["SQL", "Python", "Data Analysis", "Dashboarding"],
        "experience_min": 1,
        "experience_max": 4,
        "salary_min": 70000,
        "salary_max": 100000,
    },
    {
        "title": "UI/UX Product Designer",
        "company_name": "Paperplane Studio (Demo)",
        "location": "Remote",
        "job_type": "Contract",
        "description": "Create thoughtful user journeys and polished interfaces for web-based products.",
        "responsibilities": ["Prototype and test user flows", "Partner with engineers to refine shipped experiences"],
        "requirements": ["Portfolio demonstrating product design work", "Experience with user research"],
        "required_skills": ["Figma", "Prototyping", "User Research", "Accessibility"],
        "experience_min": 2,
        "experience_max": 6,
        "salary_min": 60000,
        "salary_max": 95000,
    },
    {
        "title": "Quality Assurance Engineer",
        "company_name": "Lighthouse Digital (Demo)",
        "location": "Chicago, IL",
        "job_type": "Full-time",
        "description": "Help deliver dependable releases by combining exploratory testing and automation.",
        "responsibilities": ["Create and maintain test plans", "Investigate defects with engineering teams"],
        "requirements": ["Experience testing web applications", "Careful, clear bug reporting"],
        "required_skills": ["QA", "Playwright", "Python", "API Testing"],
        "experience_min": 1,
        "experience_max": 4,
        "salary_min": 62000,
        "salary_max": 88000,
    },
    {
        "title": "Junior DevOps Engineer",
        "company_name": "Cloud Harbor (Demo)",
        "location": "Remote",
        "job_type": "Full-time",
        "description": "Support cloud infrastructure, deployment automation, and operational tooling.",
        "responsibilities": ["Maintain CI/CD workflows", "Help monitor and improve cloud services"],
        "requirements": ["Foundational Linux and networking knowledge", "Interest in cloud operations"],
        "required_skills": ["Linux", "Docker", "AWS", "CI/CD"],
        "experience_min": 0,
        "experience_max": 2,
        "salary_min": 60000,
        "salary_max": 82000,
    },
    {
        "title": "Machine Learning Engineer",
        "company_name": "Juniper Research (Demo)",
        "location": "Boston, MA",
        "job_type": "Full-time",
        "description": "Turn machine learning prototypes into monitored, maintainable product features.",
        "responsibilities": ["Build data and model pipelines", "Evaluate model quality and production behavior"],
        "requirements": ["Strong Python fundamentals", "Experience evaluating machine learning models"],
        "required_skills": ["Python", "Machine Learning", "SQL", "Docker"],
        "experience_min": 2,
        "experience_max": 5,
        "salary_min": 95000,
        "salary_max": 135000,
    },
    {
        "title": "Associate Product Manager",
        "company_name": "Common Ground Apps (Demo)",
        "location": "Denver, CO",
        "job_type": "Full-time",
        "description": "Coordinate product discovery and delivery for customer-facing platform features.",
        "responsibilities": ["Translate customer needs into product requirements", "Coordinate priorities across teams"],
        "requirements": ["Clear written communication", "Interest in data-informed product decisions"],
        "required_skills": ["Product Management", "Communication", "Analytics", "Agile"],
        "experience_min": 0,
        "experience_max": 3,
        "salary_min": 68000,
        "salary_max": 92000,
    },
]


async def seed_demo_jobs(database: AsyncDatabase) -> int:
    jobs = database[JOBS]
    if await jobs.count_documents({
        "status": "published",
        "is_demo": {"$ne": True},
    }):
        return 0

    now = datetime.now(timezone.utc)
    inserted = 0
    for index, role in enumerate(DEMO_ROLES):
        result = await jobs.update_one(
            {"demo_key": role["title"]},
            {
                "$setOnInsert": {
                    **role,
                    "demo_key": role["title"],
                    "is_demo": True,
                    "status": "published",
                    "created_at": now - timedelta(days=index),
                    "updated_at": now - timedelta(days=index),
                }
            },
            upsert=True,
        )
        inserted += result.upserted_id is not None
    return inserted


async def main() -> None:
    client = AsyncMongoClient(settings.mongodb_url, serverSelectionTimeoutMS=5000)
    try:
        inserted = await seed_demo_jobs(client[settings.database_name])
        if inserted:
            print(f"Added {inserted} browse-only demo jobs.")
        else:
            print("Demo jobs already exist or real published jobs are available.")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
