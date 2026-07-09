# AI Sales Pipeline Agent - Complete Documentation

## 📋 Overview

The AI Sales Pipeline Agent is a modern FastAPI-based backend application designed to manage and automate sales operations. It integrates AI capabilities (via Grok LLM), team management, lead tracking, proposal generation, email campaigns, meeting scheduling, and knowledge base management into a unified sales platform.

**Project Title:** AI Sales Pipeline Agent  
**Version:** 1.0.0  
**Python Version:** >= 3.12  
**Database:** PostgreSQL with SQLAlchemy ORM

---

## 🛠️ Tech Stack

### Core Framework
- **FastAPI**: Modern async web framework for building APIs
- **Uvicorn**: ASGI server for running FastAPI
- **SQLAlchemy >= 2.0.51**: ORM for database operations
- **Asyncpg**: Async PostgreSQL driver for non-blocking database access

### Authentication & Security
- **python-jose >= 3.5.0**: JWT token generation and validation
- **passlib >= 1.7.4**: Password hashing
- **bcrypt == 4.0.1**: Secure password encryption
- **HTTPBearer**: Bearer token authentication scheme

### Data Validation & Configuration
- **Pydantic >= 2.13.4**: Data validation and settings management
- **Pydantic[email]**: Email validation support
- **pydantic-settings >= 2.14.2**: Environment configuration management
- **python-dotenv >= 1.2.2**: Environment variable loading

### Database Migrations
- **Alembic >= 1.18.4**: Database schema versioning and migrations

### HTTP Client
- **httpx >= 0.28.1**: Async HTTP client for external API calls

### Development Tools
- **eralchemy2 >= 1.4.1**: ERD (Entity Relationship Diagram) generation

---

## 🏗️ Architecture

### Project Structure

```
app/
├── config.py                 # Configuration & settings management
├── database.py              # Database connection & session setup
├── main.py                  # Application entry point & router registration
├── core/
│   └── security.py         # JWT & password hashing utilities
├── middleware/
│   └── auth_middleware.py  # Authentication & authorization logic
├── models/                 # SQLAlchemy ORM models
│   ├── user.py
│   ├── team.py
│   ├── team_member.py
│   ├── lead.py
│   ├── leads_pool.py
│   ├── proposal.py
│   ├── meeting.py
│   ├── email.py
│   ├── chat.py
│   ├── knowledge_base.py
│   └── __init__.py
├── routers/               # API endpoint definitions
│   ├── auth.py
│   ├── teams.py
│   ├── leads.py
│   ├── proposals.py
│   ├── meetings.py
│   ├── emails.py
│   ├── knowledge_base.py
│   ├── chat.py
│   └── onboarding.py
├── schemas/              # Pydantic models for request/response validation
│   ├── auth.py
│   ├── teams.py
│   ├── leads.py
│   ├── proposals.py
│   ├── meetings.py
│   ├── emails.py
│   ├── knowledge_base.py
│   ├── chat.py
│   ├── onboarding.py
│   ├── common.py
│   └── __init__.py
└── services/            # Business logic & external service integration
    ├── auth_service.py
    ├── teams_service.py
    ├── leads_service.py
    ├── proposals_service.py
    ├── meetings_service.py
    ├── emails_service.py
    ├── knowledge_base_service.py
    ├── chat_service.py
    ├── onboarding_service.py
    └── grok_service.py
```

### Design Patterns

- **Service Layer Pattern**: Business logic separated into service classes
- **Repository Pattern**: Database queries abstracted through service methods
- **Dependency Injection**: FastAPI's `Depends()` for managing dependencies
- **Middleware Pattern**: Cross-cutting concerns (auth, error handling) via middleware
- **Async/Await**: Full async support for non-blocking operations

---

## 🗄️ Database Schema

### Core Data Models

#### **User**
- **Purpose**: Represents individual users of the platform
- **Fields**:
  - `id` (UUID, PK)
  - `full_name` (String)
  - `email` (String, unique, indexed)
  - `hashed_password` (String)
  - `created_at`, `updated_at` (DateTime)
- **Relationships**: Many teams through TeamMember

#### **Team**
- **Purpose**: Groups of users working together
- **Fields**:
  - `id` (UUID, PK)
  - `name` (String)
  - `icp` (String, optional) - Ideal Customer Profile
  - `invite_code` (String, unique)
  - `created_at` (DateTime)
- **Relationships**: Members (TeamMember), Leads, Proposals, Knowledge Assets, Chat Messages

#### **TeamMember**
- **Purpose**: Junction table linking Users to Teams with roles
- **Fields**:
  - `user_id` (UUID, FK)
  - `team_id` (UUID, FK)
  - `role` (Enum: admin, manager, rep)
  - `joined_at` (DateTime)
- **Primary Key**: Composite (user_id, team_id)

#### **Lead**
- **Purpose**: Prospect/customer records managed by the team
- **Fields**:
  - `id` (UUID, PK)
  - `team_id` (UUID, FK)
  - `name` (String, indexed)
  - `email` (String, indexed)
  - `company_name` (String, indexed)
  - `job_title` (String)
  - `source` (String)
  - `score` (Integer)
  - `status` (Enum: New, Analyzed, Qualified, Discarded, Drafted, Sent, Replied, Converted)
  - `ai_context_data` (JSONB) - Stores AI analysis metadata
  - `created_at`, `updated_at` (DateTime)
- **Relationships**: Proposals, Meetings, Emails

#### **Proposal**
- **Purpose**: Sales proposals sent to leads
- **Fields**:
  - `id` (UUID, PK)
  - `team_id` (UUID, FK)
  - `lead_id` (UUID, FK, nullable - allows orphaned proposals)
  - `company` (String)
  - `title` (String)
  - `summary` (Text)
  - `value` (Numeric)
  - `sources` (JSONB)
  - `status` (Enum: Draft, Sent, Under Review, Accepted, Rejected)
  - `outcome` (Enum: Open, Won, Lost)
  - `sent_at`, `responded_at`, `created_at`, `updated_at` (DateTime)
  - **Constraints**: CHECK on status & outcome values
- **Relationships**: Revisions, Lead, Team

#### **ProposalRevision**
- **Purpose**: Version history for proposals
- **Fields**:
  - `id` (UUID, PK)
  - `proposal_id` (UUID, FK)
  - `revision_num` (Integer)
  - `title`, `summary`, `value` (String, Text, Numeric)
  - `edited_by` (UUID)
  - `note` (String)
  - `created_at` (DateTime)

#### **ProposalTemplate**
- **Purpose**: Reusable proposal templates per team
- **Fields**:
  - `id` (UUID, PK)
  - `team_id` (UUID, FK)
  - `template_name` (String)
  - `company_name` (String)
  - `logo_url` (String)
  - `sections` (JSONB) - Template structure & content
  - `created_at`, `updated_at` (DateTime)

#### **Meeting**
- **Purpose**: Customer meetings & calls
- **Fields**:
  - `id` (UUID, PK)
  - `team_id` (UUID, FK)
  - `lead_id` (UUID, FK)
  - `client` (String)
  - `company` (String)
  - `duration` (String)
  - `date` (Date, indexed)
  - `time` (Time)
  - `timezone` (String, default: UTC)
  - `calendar_event_id` (String, optional)
  - `agenda` (JSONB)
  - `transcript` (JSONB) - Call/meeting transcript
  - `notes` (Text)
  - `recording_url` (String)
  - `status` (Enum: Scheduled, Live, Completed, Cancelled, No-Show)
  - `created_at`, `updated_at` (DateTime)
  - **Constraints**: CHECK on status values

#### **Email**
- **Purpose**: Email communications with leads
- **Fields**:
  - `id` (UUID, PK)
  - `lead_id` (UUID, FK)
  - `subject` (String)
  - `body` (Text) - HTML or plain text body
  - `status` (Enum: draft, sent)
  - `ai_metadata` (JSONB) - Stores model version, temperature, etc.
  - `sent_at` (DateTime)

#### **ChatMessage**
- **Purpose**: Conversation log between team members and AI
- **Fields**:
  - `id` (UUID, PK)
  - `team_id` (UUID, FK)
  - `user_id` (UUID)
  - `sent_by` (String) - "user" or "ai"
  - `content` (Text)
  - `metadata_log` (JSONB) - Token count, model version, latency
  - `created_at` (DateTime, indexed)
  - **Constraints**: CHECK on sent_by values

#### **KnowledgeAsset**
- **Purpose**: Documents, resources, and knowledge base items
- **Fields**:
  - `id` (UUID, PK)
  - `team_id` (UUID, FK)
  - `title` (String)
  - `type` (String, default: "Document")
  - `company` (String)
  - `date` (Date)
  - `description` (Text)
  - `tags` (JSONB)
  - `file_url` (String)
  - `source_url` (String)
  - `file_type` (String)
  - `file_size` (Text)
  - `status` (String, default: "Processing")
  - `embedding_id` (String) - Vector DB embedding reference
  - `chunk_count` (Text) - Number of chunks for retrieval
  - `created_at`, `updated_at` (DateTime)

#### **LeadPool**
- **Purpose**: Pre-qualified pool of potential leads (raw prospect data)
- **Fields**:
  - `id` (UUID, PK)
  - **Person Info**: `first_name`, `last_name`, `full_name`, `email`, `title`
  - **Company Info**: `company_name`, `website`
  - Additional prospecting metadata
  - `created_at`, `updated_at` (DateTime)

---

## 🔐 Authentication & Security

### JWT-Based Authentication

**Token Structure:**
- **Access Token**: Short-lived (24 hours), contains `sub` (user_id)
- **Refresh Token**: Long-lived (7 days), stored in httpOnly cookie
- **Algorithm**: HS256

### Password Security

- **Hashing**: bcrypt with automatic salting
- **Validation**: Passlib context for secure verification
- **Max Length**: 72 bytes (bcrypt limitation) enforced

### Authorization

**Role-Based Access Control (RBAC):**
- **Roles**: admin, manager, rep
- **Middleware**: `require_role()` decorator for endpoint protection
- **Scope**: Team-level permissions enforced through TeamMember

### Bearer Token Flow

```python
Authorization: Bearer <access_token>
```

Token validated via `get_current_user()` dependency on protected routes.

---

## 🚀 API Endpoints

### Authentication (`/auth`)

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| POST | `/auth/register` | ❌ | Register new user |
| POST | `/auth/login` | ❌ | Login & get tokens |
| POST | `/auth/logout` | ✅ | Logout (client-side cleanup) |

**Response Format:**
```json
{
  "success": boolean,
  "message": string,
  "data": object,
  "error": string | null
}
```

---

### Teams (`/teams`)

| Method | Endpoint | Auth | Role Required | Purpose |
|--------|----------|------|---------------|---------|
| GET | `/teams/` | ✅ | Any | List user's teams |
| POST | `/teams/` | ✅ | Any | Create new team |
| GET | `/teams/{team_id}` | ✅ | Any | Get team details |
| POST | `/teams/invite` | ✅ | admin, manager | Invite user to team |
| PUT | `/teams/{team_id}/members/{user_id}/role` | ✅ | admin | Update member role |
| DELETE | `/teams/{team_id}/members/{user_id}` | ✅ | admin, manager | Remove member |
| POST | `/teams/join` | ✅ | Any | Join team via invite code |
| GET | `/teams/{team_id}/invite-code` | ✅ | admin | Get team invite code |

---

### Leads (`/leads`)

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| GET | `/leads/` | ✅ | List leads (with optional status filter) |
| GET | `/leads/{lead_id}` | ✅ | Get lead details |
| POST | `/leads/` | ✅ | Create new lead |
| PATCH | `/leads/{lead_id}/status` | ✅ | Update lead status |
| POST | `/leads/{lead_id}/qualify` | ✅ | Mark lead as qualified |
| POST | `/leads/{lead_id}/discard` | ✅ | Mark lead as discarded |
| DELETE | `/leads/{lead_id}` | ✅ | Delete lead |

**Lead Statuses:**
- New, Analyzed, Qualified, Discarded, Drafted, Sent, Replied, Converted

---

### Proposals (`/proposals`)

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| GET | `/proposals/` | ✅ | List all proposals for user's team |
| GET | `/proposals/{proposal_id}` | ✅ | Get proposal details |
| POST | `/proposals/` | ✅ | Create new proposal |
| PATCH | `/proposals/{proposal_id}` | ✅ | Update proposal (title, summary, value, status, outcome) |
| POST | `/proposals/{proposal_id}/revisions` | ✅ | Add new revision to proposal |
| GET | `/proposals/template` | ✅ | Retrieve team's proposal template |
| PUT | `/proposals/template` | ✅ | Create/update proposal template |
| DELETE | `/proposals/{proposal_id}` | ✅ | Delete proposal |

**Proposal Statuses:** Draft, Sent, Under Review, Accepted, Rejected  
**Proposal Outcomes:** Open, Won, Lost

---

### Meetings (`/meetings`)

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| GET | `/meetings/` | ✅ | List all meetings |
| GET | `/meetings/{meeting_id}` | ✅ | Get meeting details |
| POST | `/meetings/` | ✅ | Create new meeting |
| PATCH | `/meetings/{meeting_id}` | ✅ | Update meeting (status, notes, transcript, agenda) |
| DELETE | `/meetings/{meeting_id}` | ✅ | Delete meeting |

**Meeting Statuses:** Scheduled, Live, Completed, Cancelled, No-Show

**Meeting Fields:**
- Client name, company, duration
- Date, time, timezone
- Agenda (array), transcript (array), notes
- Recording URL, calendar event ID

---

### Emails (`/emails`)

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| GET | `/emails/` | ✅ | List emails (with optional lead_id filter) |
| POST | `/emails/` | ✅ | Send/create email to lead |
| POST | `/emails/draft` | ✅ | Create draft email |

**Email Statuses:** draft, sent

---

### Knowledge Base (`/knowledge-base`)

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| GET | `/knowledge-base/` | ✅ | List all knowledge assets |
| GET | `/knowledge-base/{asset_id}` | ✅ | Get asset details |
| POST | `/knowledge-base/` | ✅ | Create/upload knowledge asset |
| DELETE | `/knowledge-base/{asset_id}` | ✅ | Delete asset |

**Asset Types:** Document, article, case study, pricing guide, etc.  
**Status:** Processing → Available

---

### Chat (`/chat`)

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| POST | `/chat/` | ✅ | Send message to AI & get response |

**Request:**
```json
{
  "message": "string"
}
```

**Response:**
```json
{
  "reply": "string"
}
```

---

### Onboarding (`/onboarding`)

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| POST | `/onboarding/icp` | ✅ | Submit onboarding & generate ICP |
| GET | `/onboarding/status` | ✅ | Get onboarding completion status |

**ICP (Ideal Customer Profile):** Generated by AI based on product description and target customer

---

## 🧠 Services & Business Logic

### AuthService (`auth_service.py`)
- **`register_user()`**: Create new user with email validation
- **`login_user()`**: Authenticate & generate tokens (access + refresh)
- **`logout_user()`**: Client-side cleanup (token blacklist if needed)

### LeadService (`leads_service.py`)
- **`list_leads()`**: Fetch leads for user's team with optional status filter
- **`get_lead()`**: Retrieve single lead
- **`create_lead()`**: Add new lead to team
- **`update_lead_status()`**: Change lead status and optional scoring
- **`qualify_lead()`**: Mark as qualified
- **`discard_lead()`**: Mark as discarded
- **`delete_lead()`**: Remove lead

### ProposalService (`proposals_service.py`)
- **`list_proposals()`**: Fetch all proposals
- **`get_proposal()`**: Retrieve single proposal
- **`create_proposal()`**: Generate new proposal
- **`update_proposal()`**: Modify proposal details & status
- **`add_revision()`**: Track proposal revisions
- **`get_template()`**: Retrieve team template
- **`upsert_template()`**: Create/update proposal template
- **`delete_proposal()`**: Remove proposal

### MeetingService (`meetings_service.py`)
- **`list_meetings()`**: Fetch meetings
- **`get_meeting()`**: Get meeting details
- **`create_meeting()`**: Schedule new meeting
- **`update_meeting()`**: Update meeting info & status
- **`delete_meeting()`**: Cancel/remove meeting

### EmailService (`emails_service.py`)
- **`list_emails()`**: Fetch emails (team or lead-specific)
- **`create_email()`**: Send email via AI generation
- **`draft_email()`**: Create draft without sending

### KnowledgeBaseService (`knowledge_base_service.py`)
- **`list_assets()`**: Fetch team knowledge assets
- **`get_asset()`**: Retrieve asset details
- **`create_asset()`**: Upload/add knowledge asset
- **`delete_asset()`**: Remove asset

### ChatService (`chat_service.py`)
- **`send_message()`**: Process user message & get AI response

### OnboardingService (`onboarding_service.py`)
- **`submit_onboarding()`**: Process company info & generate ICP
- **`get_onboarding()`**: Fetch onboarding status

### GrokService (`grok_service.py`)
- **AI Integration**: Calls Groq LLM API for:
  - ICP generation
  - Email content generation
  - Lead analysis & scoring
  - Proposal suggestions
  - Chat responses

### TeamsService (`teams_service.py`)
- **`create_team()`**: Initialize team with creator as admin
- **`get_team()`**: Fetch team by ID
- **`invite_member()`**: Add member via email
- **`update_member_role()`**: Change member role
- **`remove_member()`**: Delete team member
- **`join_existing_team()`**: Join via invite code
- **`get_team_invite_code()`**: Retrieve team's invite code
- **`get_user_teams()`**: List user's team memberships

---

## ⚙️ Configuration

### Environment Variables (`.env`)

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname

# JWT
JWT_SECRET=your_secret_key_here
JWT_ALGORITHM=HS256

# External APIs
GROK_API_KEY=your_grok_key
APOLLO_API_KEY=your_apollo_key
PINECONE_API_KEY=your_pinecone_key
PINECONE_INDEX_NAME=your_index_name

# AWS S3 (for file uploads)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_BUCKET_NAME=your_bucket
AWS_REGION=us-east-1

# App Config
APP_ENV=development
```

### Settings Class (`config.py`)

- Database URL with async PostgreSQL driver
- JWT configuration
- External API keys
- CORS origins (default includes localhost:3000, localhost:5173, Vercel frontend)
- Environment-based logging

---

## 🔗 External Integrations

### Groq AI (`grok_service.py`)
- **Model**: llama-3.3-70b-versatile
- **Use Cases**:
  - ICP generation from company descriptions
  - Lead qualification & analysis
  - Email content generation
  - Proposal suggestions
  - Chat assistant responses
- **API**: OpenAI-compatible REST API

### Apollo AI (Optional)
- Configured via `APOLLO_API_KEY`
- Purpose: Lead enrichment & prospecting

### Pinecone (Vector DB)
- **Purpose**: Store embeddings for knowledge assets
- **Index**: `PINECONE_INDEX_NAME`
- **Use**: Semantic search over documents

### AWS S3
- **Purpose**: File storage for documents, images, recordings
- **Buckets**: Proposal assets, meeting recordings, knowledge base files

---

## 🎯 Key Features Implemented

### 1. **User & Team Management**
   - ✅ User registration & authentication with JWT
   - ✅ Team creation with unique invite codes
   - ✅ Role-based access control (admin, manager, rep)
   - ✅ Team member invitations & role management

### 2. **Lead Management**
   - ✅ Lead CRUD operations
   - ✅ Lead status tracking (8 statuses)
   - ✅ Lead scoring & AI context storage
   - ✅ Lead qualification workflow
   - ✅ Lead deletion with cascade rules

### 3. **Proposal Management**
   - ✅ Proposal creation & updates
   - ✅ Proposal status & outcome tracking
   - ✅ Revision history with versioning
   - ✅ Proposal templates per team
   - ✅ Template customization (sections, logo, company)

### 4. **Meeting Management**
   - ✅ Meeting scheduling with date/time/timezone
   - ✅ Meeting status tracking
   - ✅ Agenda & transcript storage
   - ✅ Recording URL tracking
   - ✅ Calendar integration support

### 5. **Email Campaign Management**
  - ✅ Email creation with AI-generated content
  - ✅ Email drafting capability
  - ✅ Status tracking (draft, sent)
  - ✅ AI metadata logging

### 6. **Knowledge Base**
   - ✅ Document/asset upload & management
   - ✅ Tagging & organization
   - ✅ Embedding integration (Pinecone)
   - ✅ Multiple file types support
   - ✅ Processing status tracking

### 7. **AI Chat Assistant**
   - ✅ Real-time chat interface
   - ✅ Grok LLM integration
   - ✅ Conversation history logging
   - ✅ Metadata tracking (tokens, model version, latency)

### 8. **Onboarding Flow**
   - ✅ Product info collection
   - ✅ ICP (Ideal Customer Profile) generation
   - ✅ Onboarding status tracking

### 9. **Error Handling**
   - ✅ Standardized error responses
   - ✅ HTTPException handling with consistent format
   - ✅ Validation error handling
   - ✅ 401/403/404 status codes with proper messages

### 10. **Database Features**
   - ✅ Async PostgreSQL with connection pooling
   - ✅ Foreign key constraints with cascade rules
   - ✅ Check constraints on enum fields
   - ✅ Full-text indexing on frequently queried fields
   - ✅ JSONB storage for flexible data (AI context, metadata)
   - ✅ UUID primary keys for security

---

## 📊 Data Flow Examples

### Lead-to-Proposal Workflow
```
1. Lead created in system
2. Lead analyzed via Grok AI (context stored in ai_context_data)
3. Lead status updated based on analysis
4. Proposal created for qualified lead
5. Proposal template applied
6. Revision history tracked
7. Proposal sent (status updated)
8. Response tracked with outcome (Won/Lost)
```

### Email Campaign Flow
```
1. Contact lead in system
2. AI generates email content based on lead profile & knowledge base
3. Email saved as draft (status: draft)
4. Review & edit if needed
5. Send email (status: sent)
6. Track response & update lead status
```

### Meeting-to-Record Flow
```
1. Schedule meeting (date, time, agenda)
2. Meeting status: Scheduled
3. Join meeting → status: Live
4. Record transcript & notes
5. Meeting ends → status: Completed
6. Transcript & recording linked
7. AI summaries generated from transcript
```

---

## 🔍 Database Constraints & Rules

### Foreign Key Cascades
- **Lead deletion**: Cascades to Proposals, Meetings, Emails
- **Team deletion**: Cascades to Members, Leads, Proposals, Chat, Knowledge Assets
- **Proposal deletion**: Cascades to Revisions
- **Lead with Proposal set to NULL**: If lead deleted, proposal survives but lead_id becomes null

### Check Constraints
- **Lead Status**: Must be one of defined enum values
- **Proposal Status**: Draft, Sent, Under Review, Accepted, Rejected
- **Proposal Outcome**: Open, Won, Lost
- **Meeting Status**: Scheduled, Live, Completed, Cancelled, No-Show
- **Email Status**: draft, sent
- **ChatMessage Role**: user OR ai only

### Indexes (Performance)
- User.email (unique)
- Lead.email, Lead.name, Lead.company_name, Lead.status
- Meeting.date → efficient calendar queries
- ChatMessage.created_at → efficient message ordering
- Lead.team_id → quick team lead searches
- KnowledgeAsset.team_id → team-specific searches

---

## 🧪 Testing Considerations

### Unit Test Areas
- Password hashing/verification
- Token generation/validation
- Lead service CRUD operations
- Proposal revision tracking
- Status transition validation

### Integration Test Areas
- End-to-end user registration & login
- Team creation & member invitations
- Lead → Proposal workflow
- Email generation via Grok
- ICP generation during onboarding

### API Endpoints to Test
- Auth flows (register, login, logout)
- Team CRUD & member management
- Lead CRUD & status transitions
- Proposal CRUD & revisions
- Meeting CRUD
- Email creation
- Knowledge asset management
- Chat endpoint

---

## 🚀 Deployment Notes

### Database Setup
```sql
-- PostgreSQL required
-- Async driver: asyncpg (already configured)
-- SSL required for remote connections
```

### Environment Setup
1. Create `.env` file with all required variables
2. Run database migrations via Alembic
3. Ensure PostgreSQL is running and accessible
4. Configure external API keys (Grok, Pinecone, AWS)

### Running the App
```bash
# Install dependencies
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### CORS Configuration
- Default allowed origins include localhost:3000, localhost:5173, and Vercel frontend
- Adjustable via `FRONTEND_ORIGINS` in settings

---

## 📝 Response Format

All endpoints follow a consistent response format:

**Success (2xx):**
```json
{
  "success": true,
  "message": "Operation completed",
  "data": { /* response payload */ },
  "error": null
}
```

**Error (4xx/5xx):**
```json
{
  "success": false,
  "message": "Request failed",
  "data": null,
  "error": "Detailed error message"
}
```

---

## 🔮 Potential Future Enhancements

1. **Real-time Updates**: WebSocket support for live chat & notifications
2. **Analytics Dashboard**: Sales metrics, conversion rates, pipeline value
3. **Email Integration**: Gmail/Outlook sync for actual email sending
4. **Calendar Sync**: Google Calendar/Outlook integration for meetings
5. **Document Generation**: PDF proposal generation from templates
6. **Bulk Operations**: Import leads, batch email sending
7. **Custom Fields**: Flexible lead/proposal custom attributes
8. **Audit Logging**: Track all changes to sensitive data
9. **Advanced Search**: Full-text search on leads, proposals, emails
10. **Mobile App**: iOS/Android companion app

---

## 📚 Additional Resources

- **FastAPI Docs**: Generated at `/docs` (Swagger UI)
- **ReDoc**: Generated at `/redoc` (ReDoc UI)
- **Database Diagram**: Generated via `generate_erd.py` (uses eralchemy2)

---

## 📞 Support

For issues, questions, or contributions:
- Check existing API documentation at `/docs`
- Review models for data structure details
- Check services for business logic implementation
- Consult schemas for validation rules

---

**Last Updated**: July 8, 2026  
**Version**: 1.0.0

## issues to review
1. One logic concern in require_role
The current check passes if the user has the required role in any team they belong to. So if a user is admin in Team A but rep in Team B, they'd pass an admin check even when operating on Team B's resources.
For now this is fine since users can only be in one team (your _get_user_any_membership enforces this). But if you ever allow multi-team membership this will need to be tightened to check role within a specific team_id. Worth noting as a comment in the code.