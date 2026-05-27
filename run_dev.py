from __future__ import annotations

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        # Watch only project source/template/static folders to avoid venv churn in OneDrive.
        reload_dirs=["routers", "services", "templates", "static"],
        reload_excludes=[
            "venv",
            "venv/*",
            "*/venv/*",
            "__pycache__",
            "__pycache__/*",
            "*/__pycache__/*",
            ".pytest_cache",
            ".pytest_cache/*",
            "*.pyc",
            "*.pyo",
            "*.pyd",
            "*.db",
        ],
    )
