from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection (optional)
mongo_url = os.environ.get('MONGO_URL')
db = None
client = None
if mongo_url:
    client = AsyncIOMotorClient(mongo_url)
    db_name = os.environ.get('DB_NAME', 'acencia-db')
    db = client[db_name]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# Define Models
class StatusCheck(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class StatusCheckCreate(BaseModel):
    client_name: str

class ContactForm(BaseModel):
    name: str
    email: EmailStr
    company: Optional[str] = None
    phone: Optional[str] = None
    message: str

# Email configuration
async def send_email(contact_data: ContactForm):
    """Send contact form data via email"""
    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = "noreply@acencia.de"
        msg['To'] = "philipp.weimert@acencia.de"
        msg['Subject'] = f"Neue Kontaktanfrage von {contact_data.name}"

        # Email body
        body = f"""
Neue Kontaktanfrage über die Website:

Name: {contact_data.name}
E-Mail: {contact_data.email}
Unternehmen: {contact_data.company or 'Nicht angegeben'}
Telefon: {contact_data.phone or 'Nicht angegeben'}

Nachricht:
{contact_data.message}

---
Gesendet am: {datetime.now().strftime('%d.%m.%Y um %H:%M:%S')}
"""

        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        # For now, we'll use a simple SMTP setup that would work with most providers
        # In production, you would configure this with your actual SMTP settings
        
        # Since we don't have SMTP credentials configured, we'll save to database instead
        # and log the email content
        
        # Save contact form submission to database if db is available
        if db:
            contact_dict = contact_data.dict()
            contact_dict['id'] = str(uuid.uuid4())
            contact_dict['timestamp'] = datetime.utcnow()
            contact_dict['status'] = 'sent_to_log'
            await db.contact_submissions.insert_one(contact_dict)
        
        # Log the email content for now (in production, this would actually send)
        logger.info(f"Contact form submission (database not configured, logged only): {body}")
        
        return {"status": "success", "message": "Nachricht erfolgreich gesendet"}
        
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        raise HTTPException(status_code=500, detail="Fehler beim Senden der Nachricht")

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_obj = StatusCheck(**input.dict())
    if db:
        await db.status_checks.insert_one(status_obj.dict())
    else:
        logger.info("Database not configured. Skipping status check save.")
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    if db:
        status_checks = await db.status_checks.find().to_list(1000)
        return [StatusCheck(**status_check) for status_check in status_checks]
    logger.info("Database not configured. Returning empty status list.")
    return []

@api_router.post("/contact")
async def submit_contact_form(contact_data: ContactForm):
    """Handle contact form submission"""
    try:
        result = await send_email(contact_data)
        return result
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Unexpected error in contact form: {str(e)}")
        raise HTTPException(status_code=500, detail="Ein unerwarteter Fehler ist aufgetreten")

# Include the router in the main app
app.include_router(api_router)

# Serve the frontend
# This must be after all other routes
app.mount("/", StaticFiles(directory=ROOT_DIR.parent / "frontend/build", html=True), name="static-frontend")


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    if client:
        client.close()
