# CloudAI — System Architecture Diagrams

> Mermaid diagrams explaining the entire platform architecture, subsystems, and data flows.

---

## Table of Contents

1. [Overall System Architecture](#1-overall-system-architecture)
2. [AWS Cloud Deployment](#2-aws-cloud-deployment)
3. [AI Cognitive Agent Architecture](#3-ai-cognitive-agent-architecture)
4. [Email Data Flow (End-to-End)](#4-email-data-flow-end-to-end)
5. [Backend Component Architecture](#5-backend-component-architecture)
6. [Database Entity-Relationship Diagram](#6-database-entity-relationship-diagram)
7. [REST API Route Map](#7-rest-api-route-map)
8. [Frontend Component Tree](#8-frontend-component-tree)
9. [Celery Task & Scheduling Flow](#9-celery-task--scheduling-flow)
10. [Gmail OAuth & Sync Sequence](#10-gmail-oauth--sync-sequence)

---

## 1. Overall System Architecture

The platform is a 3-tier SaaS application deployed on AWS. Users access it through a web browser; the backend orchestrates email ingestion, AI classification, user feedback, and continuous learning.

```mermaid
graph TB
    subgraph Client["🌐 Client Layer"]
        Browser["Web Browser\n(React SPA on Vite)"]
    end

    subgraph CDN["AWS CloudFront"]
        CF["Content Delivery Network\n(static assets + SPA)"]
    end

    subgraph Frontend["Frontend SPA (React 19)"]
        Auth["Auth Flow\n(Login/Register)"]
        Inbox["Inbox View\n(Email List + Category Badges)"]
        Analytics["Analytics Dashboard\n(Accuracy Charts)"]
        AccountMgmt["Account Management\n(Connect Email)"]
    end

    subgraph Backend["Backend API (Django 5.2 + DRF)"]
        REST["REST API\n(Routers + ViewSets)"]
        AuthAPI["dj-rest-auth\nauthentication"]
        Sync["Email Sync\n(Gmail API / IMAP)"]
        NLP["NLP Engine\n(HuggingFace Zero-Shot)"]
        Critic["Critic\n(Feedback Detection)"]
        Learner["Learning Element\n(TF-IDF + LogReg)"]
    end

    subgraph Async["Background Workers"]
        CeleryWorker["Celery Worker\n(runs tasks)"]
        CeleryBeat["Celery Beat\n(periodic scheduler)"]
        Redis["Redis\n(message broker)"]
    end

    subgraph Storage["Data Layer"]
        DB[(SQLite/PostgreSQL)]
        ModelsDir["models/\n(per-user .pkl files)"]
    end

    subgraph EmailProviders["📧 Email Services"]
        Gmail["Gmail API\n(OAuth 2.0)"]
        IMAP["Generic IMAP\n(SSL)"]
    end

    Browser <-->|HTTP/HTTPS| CF
    CF --> Frontend
    Frontend <-->|API calls\nJSON| REST
    
    REST --> AuthAPI
    REST --> Sync
    REST --> Critic
    REST --> NLP
    REST --> Learner
    REST <--> DB
    
    Sync --> Gmail
    Sync --> IMAP
    
    CeleryBeat -->|triggers| CeleryWorker
    CeleryWorker <--> Redis
    CeleryWorker --> Sync
    CeleryWorker --> NLP
    CeleryWorker --> Learner
    
    NLP <--> ModelsDir
    Learner <--> ModelsDir
    
    style Client fill:#f0f4ff,stroke:#3B82F6
    style Frontend fill:#e0f2fe,stroke:#0284C7
    style Backend fill:#dcfce7,stroke:#16A34A
    style Async fill:#fef3c7,stroke:#D97706
    style Storage fill:#f3e8ff,stroke:#9333EA
    style EmailProviders fill:#ffe4e6,stroke:#E11D48
```

---

## 2. AWS Cloud Deployment

Production infrastructure on AWS using containers (ECS Fargate), managed PostgreSQL (RDS), and automated CI/CD via GitHub Actions.

```mermaid
graph TB
    subgraph User["👤 End User"]
        Browser["Browser"]
    end

    subgraph DNS["Route 53"]
        Domain["cloudai.example.com"]
    end

    subgraph CDN["CloudFront"]
        CF["CDN\n(HTTPS + Caching)"]
    end

    subgraph S3["Amazon S3"]
        Static["Static Files\n(JS, CSS, images)"]
    end

    subgraph VPC["Amazon VPC (Private Network)"]
        subgraph PublicSubnet["Public Subnet"]
            ALB["Application Load Balancer"]
        end

        subgraph PrivateSubnet["Private Subnet"]
            ECS["ECS Fargate\n(Django + Celery)"]
        end

        subgraph DataSubnet["Data Subnet"]
            RDS["RDS PostgreSQL"]
            ElastiCache["ElastiCache Redis"]
        end
    end

    subgraph CI_CD["GitHub Actions"]
        Build["Build Docker Image"]
        Push["Push to ECR"]
        Deploy["Update ECS Service"]
    end

    subgraph ECR["Amazon ECR"]
        Image["Docker Image\nRepository"]
    end

    subgraph Secrets["AWS Secrets Manager"]
        SecretKey["DJANGO_SECRET_KEY"]
        DBUrl["DATABASE_URL"]
        OAuth["OAuth Credentials"]
    end

    Browser -->|HTTPS| Domain
    Domain --> CF
    CF --> ALB
    CF --> Static
    ALB --> ECS
    ECS <--> RDS
    ECS <--> ElastiCache
    ECS --> Secrets

    Build --> Push
    Push --> Image
    Image --> Deploy
    Deploy --> ECS

    style User fill:#f0f4ff
    style VPC fill:#f8fafc,stroke:#94A3B8,stroke-dasharray: 5 5
    style CI_CD fill:#e0f2fe,stroke:#0284C7
    style Secrets fill:#fef3c7,stroke:#D97706
```

### AWS Services Used

| Service | Purpose | Estimated Cost |
|---|---|---|
| Route 53 | DNS management | ~$0.50/mo |
| CloudFront | CDN for SPA + static assets | ~$1/mo |
| ECS Fargate | Serverless Docker containers | ~$15-30/mo |
| ECR | Docker image registry | ~$0.10/mo |
| RDS (db.t3.micro) | PostgreSQL database | ~$15/mo |
| ElastiCache (t3.micro) | Redis + Celery broker | ~$13/mo |
| S3 | Static file storage | ~$0.10/mo |
| Secrets Manager | Secret storage | ~$0.40/mo |
| **Total** | | **~$45-60/mo** |

---

## 3. AI Cognitive Agent Architecture

The AI system is modeled as a **Cognitive Learning Agent** with three sub-agents forming a feedback loop, inspired by AI agent theory.

```mermaid
graph TB
    subgraph AI_Agent["🤖 Cognitive Learning Agent"]
        PE["Performance Element\n(Zero-Shot Classifier)\nHuggingFace bart-large-mnli"]
        Critic["Critic\n(Feedback Detector)\npost_save signal handler"]
        LE["Learning Element\n(TF-IDF + Logistic Regression)\nscikit-learn per-user model"]
    end

    subgraph Input["Input Stream"]
        Email["New Email\n(ingested via Gmail/IMAP)"]
        UserCorrection["User Correction\n(manual recategorization)"]
    end

    subgraph Output["Output"]
        Category["Assigned Category\n(Business, Work, Family, etc.)"]
        Confidence["Confidence Score\n(0.0 – 1.0)"]
    end

    subgraph Knowledge["Knowledge Base"]
        FeedbackDB[(FeedbackLog table)]
        Models["Per-User .pkl Files\nmodels/user_{id}_classifier.pkl"]
        Threshold["Confidence Threshold\nCLASSIFIER_CONFIDENCE_THRESHOLD = 0.4"]
    end

    Email --> PE
    PE -->|extract_email_features| TextPrep["Text Preprocessing\n(strip HTML, quotes, sig)"]
    TextPrep -->|clean text| ZeroShot["Zero-Shot Pipeline\n(classify against category names)"]
    ZeroShot -->|score >= 0.4| Category
    ZeroShot -->|score < 0.4| Uncat["Uncategorized\n(flagged for user review)"]
    ZeroShot --> Confidence

    Category --> UserCorrection
    UserCorrection --> Critic

    Critic -->|detect override| FeedbackDB
    FeedbackDB -->|unapplied records| LE

    LE -->|build training set| FeatureExtract["Feature Extraction\n(sender_domain + subject + snippet)"]
    FeatureExtract -->|texts + labels| TrainModel["Train TF-IDF + LogReg"]
    TrainModel -->|serialize| Models

    Models --> PE
    
    LE -->|mark is_applied=True| FeedbackDB

    subgraph Metrics["Accuracy Tracking"]
        MetricCalc["Accuracy = 1 - (corrections / total_classified)"]
        Timeline["Daily Accuracy Timeline"]
        Distribution["Category Distribution"]
    end

    FeedbackDB --> MetricCalc
    MetricCalc --> Timeline
    Email --> Distribution

    style AI_Agent fill:#dcfce7,stroke:#16A34A,stroke-width:2px
    style PE fill:#bbf7d0,stroke:#16A34A
    style Critic fill:#fef08a,stroke:#CA8A04
    style LE fill:#bfdbfe,stroke:#2563EB
    style Knowledge fill:#f3e8ff,stroke:#9333EA
```

### Agent Theory Mapping

| Agent Theory Concept | CloudAI Implementation |
|---|---|
| **Performance Element** | `EmailClassifier` class — HuggingFace zero-shot pipeline |
| **Critic** | `detect_category_override` signal — `post_save` on `Email` model |
| **Learning Element** | `UserClassifier` class — TF-IDF + Logistic Regression per user |
| **Knowledge Base** | `FeedbackLog` table + `models/user_{id}_classifier.pkl` files |
| **Problem Generator** | Manual user corrections — the ground truth |
| **Performance Standard** | `confidence >= 0.4` auto-assign threshold |

---

## 4. Email Data Flow (End-to-End)

The complete journey of an email from a user's inbox through the entire pipeline, including the feedback loop.

```mermaid
sequenceDiagram
    participant User as User
    participant Frontend as React SPA
    participant API as Django REST API
    participant Sync as Email Sync
    participant NLP as NLP Classifier
    participant Critic as Critic Signal
    participant Learner as Learning Element
    participant DB as Database
    participant Provider as Email Provider

    %% Phase A: Connect Account
    User->>Frontend: Connect Gmail account
    Frontend->>API: POST /api/accounts/
    API->>Provider: OAuth 2.0 flow
    Provider-->>API: access_token + refresh_token
    API->>DB: Store EmailAccount

    %% Phase B: Email Sync
    API->>Sync: enqueue sync task
    Sync->>Provider: fetch emails (Gmail API / IMAP)
    Provider-->>Sync: message list + full messages
    Sync->>DB: Create Email records (uncategorized)

    %% Phase C: AI Classification
    Sync->>NLP: classify_uncategorized_emails(user_id)
    NLP->>DB: Query uncategorized emails
    NLP->>NLP: extract_email_features()
    NLP->>NLP: zero-shot classification
    NLP->>DB: Update Email (category, confidence_score, is_ai_classified=True)

    %% Phase D: User Reviews
    User->>Frontend: View categorized inbox
    Frontend->>API: GET /api/emails/
    API-->>Frontend: Email list with category badges

    %% Phase E: User Correction (Critic Trigger)
    User->>Frontend: Change email category
    Frontend->>API: PATCH /api/emails/{id}/category/
    API->>DB: Update Email.category
    Note over Critic: post_save signal fires
    Critic->>Critic: Detect category change on AI-classified email
    Critic->>DB: Create FeedbackLog (predicted → corrected)

    %% Phase F: Learning Cycle
    Note over Learner: Periodic retrain (daily)
    Learner->>DB: Query unapplied FeedbackLog records
    Learner->>Learner: Build feature vectors
    Learner->>Learner: Train per-user TF-IDF + LogReg
    Learner->>Learner: Serialize to models/user_{id}.pkl
    Learner->>DB: Mark feedback is_applied=True

    %% Phase G: Analytics
    User->>Frontend: View AI Learning Dashboard
    Frontend->>API: GET /api/analytics/summary/
    API->>DB: Query accuracy metrics
    API-->>Frontend: Accuracy, corrections, timeline
```

---

## 5. Backend Component Architecture

Django project structure showing how modules are organized within the `apis` Django app.

```mermaid
graph TB
    subgraph Django["Django Project: aicloudproject"]
        subgraph Settings["Configuration"]
            SettingsFile["settings.py\n330 lines"]
            CeleryFile["celery.py\nCelery app"]
            Urls["urls.py\nroute wiring"]
        end

        subgraph APIS["apis app"]
            Models["models.py\n5 models"]
            Admin["admin.py\nadmin registrations"]
            
            subgraph Sync["Email Sync Module"]
                GmailSync["gmail_sync.py\nGmail API connector"]
                IMAPSync["imap_sync.py\nIMAP fallback"]
            end

            subgraph AI["AI Module"]
                TextUtils["text_utils.py\nfeature extraction"]
                Classifier["classifier.py\nzero-shot classifier"]
                Learner["learner.py\nper-user retraining"]
            end

            subgraph API["REST API Layer"]
                Serializers["serializers.py\nDRF serializers"]
                Views["views.py\nViewSets"]
                UrlsAPI["urls.py\nrouter"]
                Permissions["permissions.py\nIsOwner"]
            end

            subgraph Tasks["Background Tasks"]
                TasksFile["tasks.py\nCelery tasks"]
            end

            subgraph CriticMod["Feedback Module"]
                Signals["signals.py\npost_save signal"]
                Metrics["metrics.py\nanalytics queries"]
            end
        end
    end

    subgraph External["External Services"]
        GmailAPI["Gmail API"]
        RedisExt["Redis"]
    end

    subgraph StorageExt["Storage"]
        DB[(SQLite/PostgreSQL)]
        ModelsDir["models/ directory"]
    end

    SettingsFile --> Models
    Urls --> Views
    CeleryFile --> TasksFile

    GmailSync --> GmailAPI
    IMAPSync -->|imaplib SSL| EmailServer["IMAP Server (port 993)"]
    TasksFile --> GmailSync
    TasksFile --> IMAPSync
    TasksFile --> Classifier
    TasksFile --> Learner

    TasksFile --> RedisExt
    Classifier --> ModelsDir
    Learner --> ModelsDir
    Views --> Models

    style Django fill:#f8fafc,stroke:#64748B
    style APIS fill:#f0fdf4,stroke:#16A34A
    style External fill:#eff6ff,stroke:#3B82F6
```

### Module Dependency Map

```
tasks.py
  ├── gmail_sync.py → models.py
  ├── imap_sync.py  → models.py
  ├── text_utils.py (lazy import)
  └── classifier.py → models.py, text_utils.py
                     └── settings.py (CLASSIFIER_MODEL)

signals.py
  └── models.py (post_save on Email)

learner.py
  ├── models.py (FeedbackLog, Category)
  └── scikit-learn (TfidfVectorizer, LogisticRegression)

metrics.py
  └── models.py (Email, FeedbackLog)
```

---

## 6. Database Entity-Relationship Diagram

All 5 models and their relationships.

```mermaid
erDiagram
    User ||--o{ EmailAccount : "has many"
    User ||--o{ Category : "has many"
    User ||--o{ Email : "owns"
    User ||--o{ FeedbackLog : "generates"
    User ||--|| UserProfile : "extends"

    EmailAccount ||--o{ Email : "contains"

    Category ||--o{ Email : "classifies"
    Category ||--o{ FeedbackLog : "predicted_as"
    Category ||--o{ FeedbackLog : "corrected_to"

    Email ||--o{ FeedbackLog : "has feedback events"

    User {
        int id PK
        string username
        string email
        string password
    }

    UserProfile {
        int id PK
        int user_id FK "1:1 with User"
        string subscription_tier "free|pro|enterprise"
        bool sync_enabled
        int sync_interval_minutes "default 15"
        datetime created_at
        datetime updated_at
    }

    EmailAccount {
        int id PK
        int user_id FK
        string provider "gmail|outlook|imap"
        string email_address UK "(user, email)"
        string label
        text access_token
        text refresh_token
        datetime token_expiry
        string imap_host
        int imap_port
        string imap_username
        string imap_password
        bool imap_use_ssl
        datetime last_synced_at
        bool is_active
        datetime created_at
        datetime updated_at
    }

    Category {
        int id PK
        int user_id FK
        string name
        string slug UK "(user, slug)"
        string color "#6B7280"
        string icon
        bool is_builtin
        int display_order
        datetime created_at
    }

    Email {
        int id PK
        int user_id FK
        int email_account_id FK
        int category_id FK "nullable"
        string external_id "provider message ID"
        string thread_id
        string sender_name
        string sender_email
        string recipient_email
        string subject
        datetime received_at
        text body_text
        text body_html
        string snippet "300 chars"
        float confidence_score "0.0-1.0"
        bool is_ai_classified
        bool is_read
        bool is_archived
        datetime created_at
        datetime updated_at
        index "(user, category)"
        index "(user, received_at)"
        index "(external_id)"
    }

    FeedbackLog {
        int id PK
        int email_id FK
        int user_id FK
        int predicted_category_id FK "nullable"
        int corrected_category_id FK "nullable"
        string email_subject
        string email_sender
        string email_snippet
        bool is_applied
        datetime created_at
        index "(user, is_applied)"
    }
```

### Key Relationships

- **User → UserProfile**: One-to-one (SaaS extension)
- **User → EmailAccount**: One-to-many (multiple inboxes)
- **User → Category**: One-to-many (per-user category list)
- **User → Email**: One-to-many (all owned emails)
- **EmailAccount → Email**: One-to-many (emails from one inbox)
- **Category → Email**: One-to-many (classification)
- **Email → FeedbackLog**: One-to-many (correction history)
- **FeedbackLog → Category (x2)**: Predicted vs corrected

---

## 7. REST API Route Map

All API endpoints organized by resource, with authentication requirements and method access.

```mermaid
graph LR
    subgraph Auth["Authentication (dj-rest-auth)"]
        Login["POST /api/dj-rest-auth/login/"]
        Register["POST /api/dj-rest-auth/registration/"]
        Logout["POST /api/dj-rest-auth/logout/"]
        PwdReset["POST /api/dj-rest-auth/password/reset/"]
    end

    subgraph Profile["User Profile"]
        ProfileGET["GET /api/profile/"]
        ProfilePUT["PUT /api/profile/{id}/"]
    end

    subgraph Accounts["Email Accounts"]
        AcctList["GET /api/accounts/"]
        AcctCreate["POST /api/accounts/"]
        AcctDetail["GET /api/accounts/{id}/"]
        AcctDelete["DELETE /api/accounts/{id}/"]
        AcctSync["POST /api/accounts/{id}/sync/"]
    end

    subgraph Categories["Categories"]
        CatList["GET /api/categories/"]
        CatCreate["POST /api/categories/"]
        CatUpdate["PUT /api/categories/{id}/"]
        CatDelete["DELETE /api/categories/{id}/"]
    end

    subgraph Emails["Emails"]
        EmailList["GET /api/emails/"]
        EmailDetail["GET /api/emails/{id}/"]
        EmailUncat["GET /api/emails/uncategorized/"]
        EmailCatChange["PATCH /api/emails/{id}/category/"]
        EmailBatchCat["POST /api/emails/batch_categorize/"]
    end

    subgraph Feedback["Feedback"]
        FBList["GET /api/feedback/"]
    end

    subgraph Analytics["Analytics"]
        AnSummary["GET /api/analytics/summary/"]
        AnTimeline["GET /api/analytics/timeline/?days=30"]
        AnDistribution["GET /api/analytics/distribution/"]
        AnPending["GET /api/analytics/feedback_pending/"]
    end

    Login -->|get token| Emails
    Login --> Categories
    Login --> Accounts
    
    style Auth fill:#dbeafe,stroke:#2563EB
    style Emails fill:#dcfce7,stroke:#16A34A
    style Analytics fill:#fef3c7,stroke:#D97706

    linkStyle 0,1,2,3 stroke:#94A3B8,stroke-width:1
```

### Endpoint Summary

| Group | Count | Auth | Description |
|---|---|---|---|
| Auth | 4 | No | Registration, login, logout, password reset |
| Profile | 2 | Yes | Read/update own profile |
| Accounts | 5 | Yes | CRUD + manual sync trigger |
| Categories | 4 | Yes | CRUD (built-in protected from delete) |
| Emails | 5 | Yes | CRUD + category change + batch categorize |
| Feedback | 1 | Yes | Read-only correction history |
| Analytics | 4 | Yes | Accuracy, timeline, distribution, pending |
| **Total** | **25** | | |

---

## 8. Frontend Component Tree

React component hierarchy showing page structure, context providers, and component relationships.

```mermaid
graph TB
    subgraph App["<App /> (Root)"]
        Router["<BrowserRouter>"]
        AuthProv["<AuthProvider>\n(login state, token mgmt)"]
        subgraph Routes["<Routes>"]
            LoginPage["/login  →  <LoginPage />"]
            RegisterPage["/register  →  <RegisterPage />"]
            
            subgraph Protected["Protected Route Wrapper"]
                AppLayout["<AppLayout />\n(header + nav + logout)"]
                
                subgraph Pages["Page Components"]
                    Inbox["<InboxPage />\n/ → /inbox"]
                    Analytics["<AnalyticsPage />\n/analytics"]
                end

                subgraph InboxComponents["Inbox Sub-Components"]
                    Sidebar["Sidebar\n(category list)"]
                    EmailCard["EmailCard\n(sender, subject, badge, dropdown)"]
                    Pagination["Pagination\n(prev / next)"]
                    SearchBar["Search Bar\n(full-text search)"]
                end

                subgraph AnalyticsComponents["Analytics Sub-Components"]
                    StatsGrid["StatsGrid\n(accuracy, classified, corrections)"]
                    AccChart["AccuracyTimeChart\n(Recharts LineChart)"]
                    DistChart["CategoryPieChart\n(Recharts PieChart)"]
                end
            end
        end
    end

    Router --> AuthProv
    AuthProv --> Routes
    Routes --> LoginPage
    Routes --> RegisterPage
    Routes --> Protected
    Protected --> AppLayout
    AppLayout --> Pages

    Inbox --> SearchBar
    Inbox --> Sidebar
    Inbox --> EmailCard
    Inbox --> Pagination

    Analytics --> StatsGrid
    Analytics --> AccChart
    Analytics --> DistChart

    subgraph API["API Client Layer"]
        Client["api/client.js\n(Axios instance with Token interceptor)"]
    end

    Inbox --> Client
    Analytics --> Client
    AuthProv --> Client

    style App fill:#f0f4ff,stroke:#3B82F6
    style Protected fill:#e0f2fe,stroke:#0284C7
    style Pages fill:#dcfce7,stroke:#16A34A
    style InboxComponents fill:#fef3c7,stroke:#D97706
    style AnalyticsComponents fill:#f3e8ff,stroke:#9333EA
    style API fill:#ffe4e6,stroke:#E11D48
```

### Frontend Dependencies (package.json additions)

```
react-router-dom   →  Client-side routing (protected routes, navigation)
axios              →  HTTP client with token interceptors
recharts           →  Line charts (accuracy timeline) + Pie charts (distribution)
```

---

## 9. Celery Task & Scheduling Flow

How background tasks are scheduled, dispatched, and executed.

```mermaid
graph TB
    subgraph Schedule["Celery Beat (Scheduler)"]
        SyncSchedule["Every 15 minutes"]
        RetrainSchedule["Daily at 3 AM UTC"]
    end

    subgraph Broker["Redis (Message Broker)"]
        Queue["task queue"]
    end

    subgraph Worker["Celery Worker"]
        SyncTask["sync_all_accounts()"]
        RetrainTask["retrain_classifiers()"]
    end

    subgraph Execution["Task Execution"]
        subgraph SyncFlow["Sync Flow"]
            ForEachAccount["For each active EmailAccount"]
            Dispatch["sync_account.delay(account_id)"]
            CheckProvider["Check provider:\ngmail → gmail_sync\nimap → imap_sync\n outlook → TODO"]
            Fetch["Fetch new emails\n(max 100 per cycle)"]
            Dedup["Skip existing external_ids"]
            Save["Create Email records"]
            TriggerClassify["classify_uncategorized_emails.delay(user_id)"]
        end

        subgraph RetrainFlow["Retrain Flow"]
            CheckFeedback["Check FeedbackLog\nwhere is_applied=False"]
            GroupByUser["Group by user"]
            BuildDataset["Build (texts, labels) pairs"]
            MinSamples[">= 10 samples?"]
            Train["Train TF-IDF + LogisticRegression"]
            Serialize["Save to models/user_{id}.pkl"]
            MarkApplied["UPDATE FeedbackLog\nSET is_applied=True"]
        end

        subgraph ClassifyFlow["Classification Flow"]
            GetUncat["Query Email\nwhere is_ai_classified=False"]
            GetCat["Query user's Categories"]
            ExtractFeatures["extract_email_features()"]
            RunModel["Zero-Shot Pipeline\n(category names as labels)"]
            ScoreCheck["confidence >= 0.4?"]
            Assign["Save category + confidence_score"]
            LeaveUncat["Leave as uncategorized"]
        end
    end

    SyncSchedule --> Queue
    RetrainSchedule --> Queue
    Queue --> SyncTask
    Queue --> RetrainTask

    SyncTask --> SyncFlow
    SyncFlow --> ForEachAccount
    ForEachAccount --> Dispatch
    Dispatch --> CheckProvider
    CheckProvider --> Fetch
    Fetch --> Dedup
    Dedup --> Save
    Save --> TriggerClassify

    TriggerClassify --> ClassifyFlow
    ClassifyFlow --> GetUncat
    GetUncat --> GetCat
    GetCat --> ExtractFeatures
    ExtractFeatures --> RunModel
    RunModel --> ScoreCheck
    ScoreCheck -->|yes| Assign
    ScoreCheck -->|no| LeaveUncat

    RetrainTask --> RetrainFlow
    RetrainFlow --> CheckFeedback
    CheckFeedback --> GroupByUser
    GroupByUser --> BuildDataset
    BuildDataset --> MinSamples
    MinSamples -->|yes| Train
    Train --> Serialize
    Serialize --> MarkApplied
    MinSamples -->|no| Skip["Skip user\n(insufficient data)"]

    style Schedule fill:#fef3c7,stroke:#D97706
    style Broker fill:#f3e8ff,stroke:#9333EA
    style Worker fill:#dcfce7,stroke:#16A34A
    style Execution fill:#f8fafc,stroke:#64748B
```

---

## 10. Gmail OAuth & Sync Sequence

Detailed sequence diagram for connecting a Gmail account and the initial sync.

```mermaid
sequenceDiagram
    participant User as User
    participant Frontend as React SPA
    participant Backend as Django Backend
    participant Google as Google OAuth
    participant GmailAPI as Gmail API
    participant Celery as Celery Worker
    participant DB as Database

    User->>Frontend: Click "Connect Gmail"
    Frontend->>Backend: GET /api/accounts/gmail/start/
    Backend->>Backend: Create OAuth Flow\n(Flow.from_client_secrets_file)
    Backend-->>Frontend: { authorization_url }
    Frontend->>User: Redirect to Google consent screen

    User->>Google: Authorize (email, scopes)
    Google-->>User: Redirect to callback URL
    User->>Backend: GET /api/accounts/gmail/callback/?code=...&state=...

    Backend->>Google: Exchange auth code for tokens
    Google-->>Backend: access_token + refresh_token + expiry

    Backend->>Google: GET /oauth2/v2/userinfo
    Google-->>Backend: { email: "user@gmail.com" }

    Backend->>DB: EmailAccount.objects.update_or_create(\n    user=request.user,\n    email_address="user@gmail.com",\n    provider="gmail",\n    access_token=...,\n    refresh_token=...,\n)
    DB-->>Backend: account saved

    Backend->>Celery: sync_account.delay(account.id)
    Backend-->>Frontend: Redirect to /accounts?connected=123

    Celery->>GmailAPI: GET users.messages.list(q='in:inbox')
    GmailAPI-->>Celery: { messages: [{id: 'abc123'}, ...] }

    loop For each new message
        Celery->>GmailAPI: GET users.messages.get(id='abc123', format='full')
        GmailAPI-->>Celery: Full message payload (headers + body parts)

        Celery->>Celery: extract_headers() → subject, sender, date
        Celery->>Celery: extract_body() → body_text, body_html, snippet
        Celery->>DB: Email.objects.create(...)
    end

    Celery->>DB: EmailAccount.last_synced_at = now
    DB-->>Celery: updated

    Celery->>Celery: classify_uncategorized_emails(user_id)
    Celery->>DB: Query uncategorized emails
    Celery->>Celery: Run classifier → assign categories
    Celery->>DB: Update emails with categories

    Note over User,DB: User now sees categorized inbox
```
