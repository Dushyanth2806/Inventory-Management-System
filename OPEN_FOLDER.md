# Open the project folder

**Path:** `C:\Users\amman\inventory-system`

- [Open the project folder](file:///C:/Users/amman/inventory-system)
- [Open the backend folder](file:///C:/Users/amman/inventory-system/backend)

## From a terminal

```powershell
# Open in File Explorer
explorer C:\Users\amman\inventory-system

# Open in VS Code
code C:\Users\amman\inventory-system
```

## Layout

```text
inventory-system/
├── render.yaml          # Render deploy config
├── .gitignore
└── backend/
    ├── main.py          # FastAPI app + /api/health
    ├── config.py        # settings from .env
    ├── database.py      # MongoDB connection
    ├── schemas.py       # request validation
    ├── routers/inventory.py
    ├── services/inventory_service.py
    ├── tests/test_api.py
    ├── requirements.txt
    ├── .env             # secrets (git-ignored, never share)
    └── .env.example
```

## Run the API

```powershell
cd C:\Users\amman\inventory-system\backend
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload --port 8000
```

Then open http://127.0.0.1:8000/docs
