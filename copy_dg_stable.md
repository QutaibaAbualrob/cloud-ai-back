# CloudAI — System Architecture Diagrams

> Mermaid diagrams explaining the full platform architecture: React SPA on Vercel, Django API on AWS, AI agent loop, and data flows.

---

## Table of Contents

1. [Overall System Architecture](#1-overall-system-architecture)
2. [Deployment Topology](#2-deployment-topology)
3. [AI Cognitive Agent Architecture](#3-ai-cognitive-agent-architecture)
4. [Email Data Flow (End-to-End)](#4-email-data-flow-end-to-end)
5. [Backend Component Architecture](#5-backend-component-architecture)
6. [Database Entity-Relationship Diagram](#6-database-entity-relationship-diagram)
7. [REST API Route Map](#7-rest-api-route-map)
8. [Frontend Component Tree](#8-frontend-component-tree)
9. [Celery Task & Scheduling Flow](#9-celery-task--scheduling-flow)
10. [Gmail OAuth & Sync Sequence](#10-gmail-oauth--sync-sequence)

---

## **1. Overall System Architecture**

> 🌐 **Architecture**: React SPA on Vercel → Django API on AWS

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'lineColor': '#334155', 'primaryTextColor': '#e5e7eb', 'primaryColor': '#1e293b', 'tertiaryColor': '#0f172a'}}}%%
graph TB
    Browser["User Browser\nCloudAI SPA via Vercel CDN"]

    subgraph Vercel["Vercel (Frontend)"]
        Vite["React SPA\n(Vite build → dist/)"]
        VConfig["vercel.json\nrewrites: /* → /index.html"]
        VEnv["VITE_API_BASE\nproduction API URL"]
        GitHub["GitHub Push\n→ auto-deploy"]
    end

    subgraph AWS["AWS Cloud (Backend)"]
        subgraph API["Django REST API"]
            Layer["DRF ViewSets\n· views.py / urls.py\n· serializers.py\n· permissions.py"]
        end

        subgraph Engine["Core Engine (apis app)"]
            Classifier["classifier.py\nPerformance Element\nLLM API client"]
            Critic["signals.py\nCritic\npre_save on Email"]
            Learner["learner.py\nLearning Element\nUserPreferenceMemory"]
            Digest["digest.py\nThread + Digest\ncontext tracking"]
            Gmail["gmail_sync.py\nGmail OAuth connector"]
            IMAP["imap_sync.py\nIMAP fallback"]
        end

        RDS["RDS PostgreSQL\nUser · Email · Category\nFeedbackLog · Thread"]
        Redis["ElastiCache Redis\nCelery Broker · Cache"]
        SM["Secrets Manager\nSECRET_KEY · DB creds\nOAuth · LLM_API_KEY"]
    end

    Browser -->|HTTPS REST JSON| Vite
    GitHub -.-> Vite
    VEnv -.->|CORS| Layer

    Vite --> Layer
    Layer --> Classifier
    Layer --> Critic
    Layer --> Learner

    Classifier -.-> Digest
    Critic --> Learner
    Learner -.->|hints| Classifier

    Gmail --> Classifier
    IMAP --> Classifier
    Digest --> Classifier

    Layer <--> RDS
    Classifier <--> RDS
    Critic <--> RDS
    Learner <--> RDS

    Layer -.-> Redis
    Classifier -.-> Redis

    Layer --> SM
    Classifier --> SM

    style Browser fill:#0f172a,stroke:#6366f1,color:#e5e7eb
    style Vercel fill:#0f172a,stroke:#22c55e,color:#e5e7eb
    style AWS fill:#0f172a,stroke:#3b82f6,color:#e5e7eb
    style API fill:#1e293b,stroke:#6366f1,color:#e5e7eb
    style Engine fill:#1e293b,stroke:#818cf8,color:#e5e7eb
    style Classifier fill:#064e3b,stroke:#22c55e,color:#e5e7eb
    style Critic fill:#451a03,stroke:#f59e0b,color:#e5e7eb
    style Learner fill:#1e1b4b,stroke:#818cf8,color:#e5e7eb
    style RDS fill:#1e293b,stroke:#3b82f6,color:#e5e7eb
    style Redis fill:#1e293b,stroke:#f59e0b,color:#e5e7eb
    style SM fill:#1e293b,stroke:#94a3b8,color:#e5e7eb
```

### Services Summary

| Provider | Service | Purpose | Est. Cost |
|---|---|---|---|
| **Vercel** | Edge CDN + auto-deploy | Host React SPA, GitHub integration | Free (Hobby) |
| **AWS** | ECS Fargate | Django + Celery containers | ~$15-30/mo |
| **AWS** | RDS PostgreSQL | Production database | ~$15/mo |
| **AWS** | ElastiCache Redis | Celery broker + cache | ~$13/mo |
| **AWS** | Secrets Manager | Encrypted secrets | ~$0.40/mo |
| **AWS** | Route 53 | DNS (api.cloudai.com) | ~$0.50/mo |
| **Total** | | | **~$45-60/mo** |

---

## **2. Deployment Topology**

> 🚀 **CI/CD**: Vercel auto-deploys frontend; GitHub Actions deploys backend

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'lineColor': '#334155', 'primaryTextColor': '#e5e7eb', 'primaryColor': '#1e293b', 'tertiaryColor': '#0f172a'}}}%%
graph TB
    subgraph GitHub["GitHub Repository"]
        Repo["cloudai-project"]
    end

    subgraph Vercel["Vercel (Frontend)"]
        direction TB
        VA["Auto-deploy on push"]
        VConfig["vercel.json\nrewrites: /* → /index.html"]
        VEnv["VITE_API_BASE\n= api.cloudai.com"]
        VBuild["npm run build → dist/"]
    end

    subgraph AWS["AWS Cloud (Backend)"]
        direction TB
        Route53["Route 53\napi.cloudai.com"]
        ALB["Application Load Balancer"]
        
        subgraph ECS["ECS Fargate"]
            API["Django API\ngunicorn + uvicorn"]
            Worker["Celery Worker"]
            Beat["Celery Beat\n15min / daily"]
        end

        RDS["RDS PostgreSQL"]
        Redis["ElastiCache Redis"]
        SM["Secrets Manager"]
    end

    subgraph CI_CD["GitHub Actions"]
        Build["Docker build"]
        ECR["Push to ECR"]
        Deploy["Update ECS service"]
    end

    Repo -->|main push| VA
    VA --> VBuild
    VBuild --> VConfig

    Repo -->|main push| Build
    Build --> ECR
    ECR --> Deploy
    Deploy --> ECS

    VEnv -.->|CORS| API
    Route53 --> ALB
    ALB --> API
    API <--> RDS
    API <--> Worker
    Worker <--> Redis
    Beat --> Worker
    API --> SM
    Worker --> SM

    style GitHub fill:#1e293b,stroke:#6366f1,color:#e5e7eb
    style Vercel fill:#0f172a,stroke:#22c55e,color:#e5e7eb
    style AWS fill:#0f172a,stroke:#3b82f6,color:#e5e7eb
    style CI_CD fill:#1e293b,stroke:#f59e0b,color:#e5e7eb
```

---

## **3. AI Cognitive Agent Architecture**

> 🤖 **Agent theory**: Performance Element → Critic → Learning Element

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'lineColor': '#334155', 'primaryTextColor': '#e5e7eb', 'primaryColor': '#1e293b', 'tertiaryColor': '#0f172a'}}}%%
graph TB
    subgraph Agent["Cognitive Learning Agent"]
        PE["Performance Element\n(classifier.py)\nLLM API + preference hints"]
        Critic["Critic\n(signals.py)\npre_save on Email"]
        LE["Learning Element\n(learner.py)\nUserPreferenceMemory"]
    end

    subgraph Input["Input Stream"]
        Email["New Email\n(ingested via sync)"]
        Correction["User Correction\n(manual recategorization)"]
    end

    subgraph Output["Output"]
        Category["Assigned Category"]
        Confidence["Confidence Score\n0.0 – 1.0"]
        Summary["AI Summary"]
        Priority["Priority: low/med/high"]
        Urgency["is_urgent · has_deadline"]
        ActionItems["Action Items"]
    end

    subgraph Knowledge["Knowledge Base"]
        FB[(FeedbackLog table)]
        Hints["Preference Hints\n(1-15 lines plain English)"]
        Threshold["Threshold: conf ≥ 0.4\n→ assign category\nconf < 0.4 → Miscellaneous"]
    end

    Email --> PE
    PE -->|extract_clean_body| TextPrep["Text Preprocessing\nstrip HTML / quotes / sigs"]
    TextPrep -->|clean text ≤ 4000 chars| LLM["LLM API Call\nchat completions"]
    LLM -->|score ≥ 0.4| Category
    LLM -->|score < 0.4| Misc["Miscellaneous catch-all"]
    LLM --> Confidence
    LLM --> Summary
    LLM --> Priority
    LLM --> Urgency
    LLM --> ActionItems

    Category --> Correction
    Correction --> Critic
    Critic -->|detect override| FB
    FB -->|unapplied records| LE
    LE -->|extract patterns| BuildHints["sender domain → category\noverride directions\ncategory frequencies"]
    BuildHints -->|≥2 corrections per pattern| Hints
    Hints -->|injected into prompt| PE

    FB --> Metrics["Accuracy = 1 - (corrections / total_classified)"]

    style Agent fill:#0f172a,stroke:#6366f1,stroke-width:2px,color:#e5e7eb
    style PE fill:#064e3b,stroke:#22c55e,color:#e5e7eb
    style Critic fill:#451a03,stroke:#f59e0b,color:#e5e7eb
    style LE fill:#1e1b4b,stroke:#818cf8,color:#e5e7eb
```

### Agent Theory Mapping

| Concept | CloudAI Implementation |
|---|---|
| **Performance Element** | `EmailClassifier` — LLM API (OpenAI-compatible) |
| **Critic** | `pre_save` signal on `Email` model |
| **Learning Element** | `UserPreferenceMemory` — pattern extraction |
| **Knowledge Base** | `FeedbackLog` table + preference hints |
| **Performance Standard** | Confidence threshold: 0.4 |
| **Environment** | User's inbox (Gmail/IMAP/Outlook) |

---

## **4. Email Data Flow (End-to-End)**

> ⏱ **Pipeline**: Connect → Sync → Classify → Review → Learn

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'lineColor': '#818cf8', 'primaryTextColor': '#e5e7eb', 'primaryColor': '#1e293b', 'tertiaryColor': '#0f172a', 'actorBorder': '#818cf8', 'actorBkg': '#1e293b', 'actorTextColor': '#e5e7eb', 'actorLineColor': '#818cf8', 'signalColor': '#818cf8', 'signalTextColor': '#e5e7eb', 'labelBoxBkgColor': '#1e293b', 'labelBoxBorderColor': '#6366f1', 'noteBkgColor': '#1e293b', 'noteTextColor': '#9ca3af', 'noteBorderColor': '#475569', 'activationBorderColor': '#6366f1', 'activationBkgColor': '#0f172a'}}}%%
sequenceDiagram
    participant User as User
    participant SPA as React SPA (Vercel)
    participant API as Django REST API
    participant Sync as Email Sync
    participant NLP as LLM Classifier
    participant Critic as Critic Signal
    participant Learner as Learning Element
    participant DB as Database
    participant Provider as Email Provider

    %% Phase A: Connect Account
    User->>SPA: Connect Gmail account
    SPA->>API: POST /api/accounts/
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
    NLP->>NLP: extract_clean_body()
    NLP->>NLP: LLM API → category + summary + priority
    NLP->>DB: Update Email with LLM fields

    %% Phase D: User Reviews
    User->>SPA: View categorized inbox
    SPA->>API: GET /api/emails/
    API-->>SPA: Email list with badges + AI summary

    %% Phase E: User Correction (Critic Trigger)
    User->>SPA: Change email category
    SPA->>API: PATCH /api/emails/{id}/category/
    API->>DB: Update Email.category
    Note over Critic: pre_save signal fires
    Critic->>Critic: Detect AI-classified category change
    Critic->>DB: Create FeedbackLog

    %% Phase F: Learning Cycle
    Note over Learner: On next classification cycle
    Learner->>DB: Query all FeedbackLog records
    Learner->>Learner: Extract sender-domain patterns
    Learner->>Learner: Build preference hints (≤15 lines)
    Learner->>NLP: Inject hints into LLM prompt

    %% Phase G: Analytics
    User->>SPA: Open Dashboard / Analytics
    SPA->>API: GET /api/analytics/summary/
    API->>DB: Query accuracy metrics
    API-->>SPA: Accuracy, timeline, distribution
```

---

## **5. Backend Component Architecture**

> 🏗️ **Module layout**: Django project with `apis` app + Celery workers

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'lineColor': '#334155', 'primaryTextColor': '#e5e7eb', 'primaryColor': '#1e293b', 'tertiaryColor': '#0f172a'}}}%%
graph TB
    subgraph Django["Django Project"]
        subgraph Config["Configuration"]
            Settings["settings.py\nEnviron vars from .env"]
            CeleryCfg["celery.py\nCelery app instance"]
            Urls["urls.py\nRoute wiring"]
            Init["__init__.py\nCelery conditional import"]
        end

        subgraph App["apis app"]
            Models["models.py\n6 models + indexes"]
            Admin["admin.py\nAdmin registrations"]

            subgraph SyncMod["Sync Module"]
                Gmail["gmail_sync.py\nGmail API connector"]
                IMAP["imap_sync.py\nIMAP fallback"]
            end

            subgraph AIMod["AI Module"]
                TextUtils["text_utils.py\nBody cleaning"]
                Classifier["classifier.py\nLLM API client"]
                Learner["learner.py\nPref memory"]
            end

            subgraph API["API Layer"]
                Serializers["serializers.py\n8 serializers"]
                Views["views.py\n6 ViewSets"]
                UrlsAPI["urls.py\nDRF DefaultRouter"]
                Permissions["permissions.py\nIsOwner"]
            end

            subgraph Feedback["Feedback & Analytics"]
                Signals["signals.py\npre_save critic"]
                Metrics["metrics.py\nAccuracy queries"]
                Digest["digest.py\nThread + digest"]
            end

            subgraph Tasks["Background Tasks"]
                TasksFile["tasks.py\n5 Celery tasks"]
            end
        end
    end

    subgraph External["External Services"]
        GmailAPI["Gmail API\n(OAuth 2.0)"]
        IMAPServer["IMAP Server\n(port 993)"]
        LLM["LLM API\n(OpenAI-compatible)"]
        Redis["Redis\n(Broker + Cache)"]
    end

    Settings --> Models
    Urls --> Views
    CeleryCfg --> TasksFile
    Init -.-> CeleryCfg

    Gmail --> GmailAPI
    IMAP --> IMAPServer
    TasksFile --> Gmail
    TasksFile --> IMAP
    TasksFile --> Classifier
    TasksFile --> Learner
    TasksFile --> Digest
    Classifier --> LLM
    Digest --> LLM
    TasksFile --> Redis

    style Django fill:#0f172a,stroke:#6366f1,color:#e5e7eb
    style App fill:#1e293b,stroke:#22c55e,color:#e5e7eb
    style External fill:#1e1b4b,stroke:#818cf8,color:#e5e7eb
```

### Module Dependency Map

```
tasks.py
  ├── gmail_sync.py → models.py
  ├── imap_sync.py  → models.py
  ├── text_utils.py (lazy import)
  ├── classifier.py → models.py, text_utils.py
  │                 └── settings.py (LLM_API_URL, KEY, MODEL)
  ├── digest.py     → models.py, classifier.py (LLM call)
  └── learner.py    → models.py (FeedbackLog, Category)

signals.py → models.py (pre_save on Email)
metrics.py → models.py (Email, FeedbackLog)
```

---

## **6. Database Entity-Relationship Diagram**

> 🗃️ **Data model**: 6 models, 5 indexes, 9 relationships

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'lineColor': '#334155', 'primaryTextColor': '#e5e7eb', 'primaryColor': '#1e293b', 'tertiaryColor': '#0f172a'}}}%%
erDiagram
    User ||--o{ EmailAccount : "has many"
    User ||--o{ Category : "has many"
    User ||--o{ Email : "owns"
    User ||--o{ FeedbackLog : "generates"
    User ||--o{ EmailThread : "has threads"
    User ||--|| UserProfile : "extends"

    EmailAccount ||--o{ Email : "contains"
    EmailAccount ||--o{ EmailThread : "has threads"

    Category ||--o{ Email : "classifies"
    Category ||--o{ FeedbackLog : "predicted_as"
    Category ||--o{ FeedbackLog : "corrected_to"

    Email ||--o{ FeedbackLog : "has feedback"

    Email ||--o{ EmailThread : "belongs to"

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
        int sync_interval_minutes
        datetime created_at
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
    }

    Category {
        int id PK
        int user_id FK
        string name
        string slug UK "(user, slug)"
        string color
        bool is_builtin
        int display_order
    }

    Email {
        int id PK
        int user_id FK
        int email_account_id FK
        int category_id FK "nullable"
        string external_id
        string thread_id
        string sender_name
        string sender_email
        string recipient_email
        string subject
        datetime received_at
        text body_text
        text body_html
        string snippet
        string summary "LLM-generated"
        string priority "low|medium|high"
        bool is_urgent "LLM"
        bool has_deadline "LLM"
        datetime deadline_date "LLM"
        text action_items "LLM"
        float confidence_score
        bool is_ai_classified
        bool is_read
        bool is_archived
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
    }

    EmailThread {
        int id PK
        int user_id FK
        int email_account_id FK
        string thread_id UK "(user, thread_id)"
        string subject
        text participants
        text summary "LLM merged"
        int email_count
        datetime latest_received_at
    }
```

### Key Relationships

- **User → UserProfile**: One-to-one (SaaS extension)
- **User → EmailAccount**: One-to-many (multiple inboxes)
- **User → Category**: One-to-many (per-user categories)
- **User → Email**: One-to-many (all user emails)
- **EmailAccount → Email**: One-to-many (emails from one inbox)
- **Category → Email**: One-to-many (nullable, SET_NULL on delete)
- **Email → FeedbackLog**: One-to-many (correction history)
- **FeedbackLog → Category (×2)**: Predicted vs corrected
- **User → EmailThread**: One-to-many (thread context)

---

## **7. REST API Route Map**

> 🔌 **Endpoints**: 25 routes across 7 resource groups

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'lineColor': '#334155', 'primaryTextColor': '#e5e7eb', 'primaryColor': '#1e293b', 'tertiaryColor': '#0f172a'}}}%%
graph LR
    subgraph Auth["Auth (dj-rest-auth)"]
        L["POST /login/"]
        R["POST /registration/"]
        O["POST /logout/"]
    end

    subgraph Emails[" /emails/"]
        EL["GET / → list"]
        ED["GET /{id}/ → detail"]
        EC["PATCH /{id}/category/"]
        EU["GET /uncategorized/"]
        EB["POST /batch_categorize/"]
    end

    subgraph Cats[" /categories/"]
        CL["GET / → list"]
        CC["POST / → create"]
        CU["PUT /{id}/"]
        CD["DELETE /{id}/"]
    end

    subgraph Acc[" /accounts/"]
        AL["GET / → list"]
        AC["POST / → create"]
        AD["DELETE /{id}/"]
        AS["POST /{id}/sync/"]
    end

    subgraph Analytics[" /analytics/"]
        S["GET /summary/"]
        T["GET /timeline/?days=30"]
        D["GET /distribution/"]
        DG["GET /digest/?days=1"]
        CDG["GET /category_digest/"]
        U["GET /urgent/"]
        FP["GET /feedback_pending/"]
    end

    subgraph FB[" /feedback/"]
        FBL["GET / → list"]
    end

    Auth --> Emails
    Auth --> Cats
    Auth --> Acc
    Auth --> Analytics

    style Auth fill:#1e293b,stroke:#3b82f6,color:#e5e7eb
    style Emails fill:#064e3b,stroke:#22c55e,color:#e5e7eb
    style Analytics fill:#451a03,stroke:#f59e0b,color:#e5e7eb
    style Cats fill:#1e1b4b,stroke:#818cf8,color:#e5e7eb
    style Acc fill:#1e293b,stroke:#6366f1,color:#e5e7eb
    style FB fill:#0f172a,stroke:#94a3b8,color:#e5e7eb
```

| Group | Count | Auth | Auth Header |
|---|---|---|---|
| Auth | 3 | No | — |
| Emails | 5 | Yes | `Authorization: Token <key>` |
| Categories | 4 | Yes | Same |
| Accounts | 4 | Yes | Same |
| Analytics | 7 | Yes | Same |
| Feedback | 1 | Yes | Same |
| **Total** | **24** | | |

---

## **8. Frontend Component Tree**

> 🖥️ **UI hierarchy**: React 19 SPA with 7 protected routes

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'lineColor': '#334155', 'primaryTextColor': '#e5e7eb', 'primaryColor': '#1e293b', 'tertiaryColor': '#0f172a'}}}%%
graph TB
    subgraph Root["<App />"]
        Router["<BrowserRouter>"]
        Auth["<AuthProvider>\n(token + user state)"]
        
        subgraph Routes["<Routes> (7 pages + redirect)"]
            Login["/login  →  <LoginPage />"]
            Register["/register  →  <RegisterPage />"]
            
            subgraph Protected["<ProtectedRoute> wrapper"]
                Layout["<AppLayout />\nHeader + Sidebar + Main"]

                subgraph Pages["Page Components (5)"]
                    Dash["<DashboardPage />\nStats + Digest + Urgent"]

                    Inbox["<InboxPage />\nEmails + Filter + Detail"]
                    InboxC["Sub-components:\n· EmailCard[] expand-to-detail\n· CategoryFilterSidebar\n· SearchBar\n· Pagination"]
                    
                    Analytics["<AnalyticsPage />\nCharts + Digest Gen"]
                    AnalyticsC["Sub-components:\n· AccuracyLineChart (Recharts)\n· CategoryPieChart (Recharts)\n· DigestGeneratorPanel\n· UrgentItemsPanel"]
                    
                    Accounts["<AccountsPage />\nConnect/Sync/Remove"]
                    Cats["<CategoriesPage />\nCRUD with color picker"]
                    Feedback["<FeedbackPage />\nCorrections table"]
                end
            end
        end

        Client["api/client.js\nAxios: Token interceptor + 401 redirect"]
    end

    Router --> Auth
    Auth --> Routes
    Routes --> Login
    Routes --> Register
    Routes --> Protected
    Protected --> Layout
    Layout --> Pages

    Inbox --> InboxC
    Analytics --> AnalyticsC

    Pages --> Client

    style Root fill:#0f172a,stroke:#6366f1,color:#e5e7eb
    style Protected fill:#1e293b,stroke:#22c55e,color:#e5e7eb
    style Pages fill:#1e1b4b,stroke:#818cf8,color:#e5e7eb
    style InboxC fill:#451a03,stroke:#f59e0b,color:#e5e7eb
    style AnalyticsC fill:#064e3b,stroke:#22c55e,color:#e5e7eb
    style Client fill:#1e293b,stroke:#94a3b8,color:#e5e7eb
```

### Frontend Dependencies

```
react-router-dom  →  Routing + NavLink active-state
axios             →  HTTP with token interceptors
recharts          →  LineChart + PieChart (dark theme tooltips)
```

### CSS Architecture (modular)

```
index.css  →  Dark theme :root vars, reset, shared components (.badge, .btn-*, .form-*, .card, .modal-*)
App.css    →  Layout only: header, sidebar, main-content
Pages:
  LoginPage.css | DashboardPage.css | InboxPage.css
  AnalyticsPage.css | AccountsPage.css | CategoriesPage.css | FeedbackPage.css
```

---

## **9. Celery Task & Scheduling Flow**

> ⏰ **Background jobs**: Beat (15min/daily) → Redis broker → Worker executes

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'lineColor': '#334155', 'primaryTextColor': '#e5e7eb', 'primaryColor': '#1e293b', 'tertiaryColor': '#0f172a'}}}%%
graph TB
    subgraph Schedule["Celery Beat (Scheduler)"]
        S15["Every 15 minutes"]
        Daily["Daily at midnight"]
    end

    subgraph Broker["Redis (Message Broker)"]
        Q["task queue"]
    end

    subgraph Worker["Celery Worker"]
        SyncAll["sync_all_accounts()"]
        DailyDigest["generate_daily_digest_for_all_users()"]
        Refresh["refresh_preference_memories()"]
    end

    subgraph SyncFlow["Sync Flow"]
        ForEach["For each active EmailAccount"]
        Dispatch["sync_account.delay(account_id)"]
        Check["Gmail → gmail_sync()\nIMAP → imap_sync()"]
        Fetch["Fetch new emails\n(max 100 per cycle)"]
        Dedup["Skip existing external_ids"]
        Save["Create Email records"]
        Classify["classify_uncategorized_emails.delay(user_id)"]
    end

    subgraph ClassifyFlow["Classification Flow"]
        GetUncat["Query Email\nwhere is_ai_classified=False"]
        BuildHints["Build UserPreferenceMemory\nfrom FeedbackLog"]
        Clean["extract_clean_body()\nstrip HTML/quotes/sigs"]
        LLMCall["LLM API → category, confidence,\nsummary, priority, urgency,\ndeadline, action_items"]
        CheckConf{"confidence ≥ 0.4?"}
        Assign["Save category + LLM fields"]
        Fallback["Assign to 'Miscellaneous'"]
        UpdateThread["update_thread_context()\ncreate/merge EmailThread"]
    end

    S15 --> Q
    Daily --> Q
    Q --> SyncAll
    Q --> DailyDigest
    Q --> Refresh

    SyncAll --> SyncFlow
    SyncFlow --> ForEach
    ForEach --> Dispatch
    Dispatch --> Check
    Check --> Fetch
    Fetch --> Dedup
    Dedup --> Save
    Save --> Classify

    Classify --> ClassifyFlow
    ClassifyFlow --> GetUncat
    GetUncat --> BuildHints
    BuildHints --> Clean
    Clean --> LLMCall
    LLMCall --> CheckConf
    CheckConf -->|yes| Assign
    CheckConf -->|no| Fallback
    Assign --> UpdateThread
    Fallback --> UpdateThread

    DailyDigest -->|per user| GenDigest["LLM API → daily_overview,\nurgent_items, deadlines,\ncategory_highlights"]
    Refresh -->|per user| Log["Log users with\naccumulated feedback"]

    style Schedule fill:#451a03,stroke:#f59e0b,color:#e5e7eb
    style Broker fill:#1e1b4b,stroke:#818cf8,color:#e5e7eb
    style Worker fill:#064e3b,stroke:#22c55e,color:#e5e7eb
    style SyncFlow fill:#1e293b,stroke:#3b82f6,color:#e5e7eb
    style ClassifyFlow fill:#0f172a,stroke:#6366f1,color:#e5e7eb
```

---

## **10. Gmail OAuth & Sync Sequence**

> 🔐 **Auth flow**: OAuth 2.0 consent → token exchange → initial sync → classification

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'lineColor': '#818cf8', 'primaryTextColor': '#e5e7eb', 'primaryColor': '#1e293b', 'tertiaryColor': '#0f172a', 'actorBorder': '#818cf8', 'actorBkg': '#1e293b', 'actorTextColor': '#e5e7eb', 'actorLineColor': '#818cf8', 'signalColor': '#818cf8', 'signalTextColor': '#e5e7eb', 'labelBoxBkgColor': '#1e293b', 'labelBoxBorderColor': '#6366f1', 'noteBkgColor': '#1e293b', 'noteTextColor': '#9ca3af', 'noteBorderColor': '#475569', 'activationBorderColor': '#6366f1', 'activationBkgColor': '#0f172a'}}}%%
sequenceDiagram
    participant User as User
    participant SPA as React SPA
    participant API as Django API
    participant Google as Google OAuth
    participant GmailAPI as Gmail API
    participant Celery as Celery Worker
    participant DB as Database
    participant LLM as LLM API

    User->>SPA: Click "Connect Gmail"
    SPA->>API: POST /api/accounts/

    Note over API,Google: OAuth 2.0 flow
    API->>Google: Redirect to consent screen
    Google-->>User: Authorize (email, scopes)
    User->>Google: Grant access
    Google-->>API: Authorization code → tokens

    API->>Google: GET /oauth2/v2/userinfo
    Google-->>API: { email: "user@gmail.com" }

    API->>DB: Create EmailAccount(provider=gmail, tokens)
    DB-->>API: account saved

    API-->>SPA: Account connected (id, status)
    SPA-->>User: Account shown in list

    API->>Celery: sync_account.delay(account.id)

    Celery->>GmailAPI: GET users.messages.list(q='in:inbox')
    GmailAPI-->>Celery: { messages: [{id: 'abc'}, ...] }

    loop Each new message (max 100)
        Celery->>GmailAPI: GET users.messages.get(id='abc', format='full')
        GmailAPI-->>Celery: Full message (payload, MIME parts)
        Celery->>Celery: extract_headers() → subject, sender, date
        Celery->>Celery: extract_body() → body_text, snippet
        Celery->>DB: Email.objects.create(external_id=..., category=NULL)
    end

    Celery->>DB: EmailAccount.last_synced_at = now

    Note over Celery,LLM: Classification pipeline
    Celery->>DB: Query uncategorized emails
    Celery->>DB: Query FeedbackLog for preference hints
    Celery->>Celery: clean body (strip HTML/quotes)
    Celery->>LLM: Chat completions API
    LLM-->>Celery: { category, confidence, summary, priority, ... }
    Celery->>DB: Update Email with AI fields
    Celery->>DB: Update/create EmailThread

    Note over User,DB: Email now visible in inbox with AI analysis
```

---

## Legend

| Symbol | Meaning |
|---|---|
| `--▶` | Data flow / dependency |
| `--1:1--` | One-to-one relationship |
| `--o{` | One-to-many relationship |
| `(LLM)` | Field generated by LLM API |
| `[protected]` | Route behind `<ProtectedRoute>` |
