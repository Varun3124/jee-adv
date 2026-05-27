# JEE Advanced 2026 Project Summary

## Overview
This project is a FastAPI application for analyzing JEE Advanced response sheets, scoring submissions, estimating rank, and predicting possible JoSAA outcomes. It uses SQLite through SQLAlchemy, renders pages with Jinja2 templates, and exposes JSON endpoints for charts and prediction data.

## Core Application Files
- [main.py](main.py) initializes the FastAPI app, sets up lifespan startup, mounts static assets, and registers the student, API, and admin routers.
- [config.py](config.py) loads environment settings such as database URL, admin credentials, candidate count, and rank buffer percentage.
- [database.py](database.py) defines the SQLAlchemy async engine, session factory, base model class, and database initialization routine.
- [models.py](models.py) defines the persistence layer for answer keys, response sheets, question responses, JoSAA closing ranks, and app config values.
- [schemas.py](schemas.py) contains Pydantic models for parsed papers, parsed questions, and evaluation results.
- [requirements.txt](requirements.txt) lists the project dependencies.
- [.env.example](.env.example) documents the expected environment variables.
- [jee_advanced_2026.db](jee_advanced_2026.db) is the local SQLite database file used by default.

## Routers
- [routers/student.py](routers/student.py) handles the public UI: home page, response-sheet submission, analysis page, question-wise analysis page, and rank page.
- [routers/api.py](routers/api.py) serves JSON data for section breakdowns, score distribution charts, question details, and JoSAA prediction results.
- [routers/admin.py](routers/admin.py) provides the protected admin console for answer-key management, bulk ingestion, JoSAA import, config updates, and pool reset.
- [routers/__init__.py](routers/__init__.py) is empty and exists only to mark the package.

## Services
- [services/parser.py](services/parser.py) fetches DigiAlm response sheets and parses candidate metadata, sections, and question responses from HTML.
- [services/evaluator.py](services/evaluator.py) scores each question against the answer key, supports single, multiple, numeric, and text answers, and aggregates paper and section totals.
- [services/submissions.py](services/submissions.py) combines parsing and evaluation, deduplicates submissions with a stable hash, stores the response sheet, and writes per-question results.
- [services/rank.py](services/rank.py) computes rank estimates, percentile, score distributions, question difficulty, and manages app config values.
- [services/josaa.py](services/josaa.py) parses JoSAA CSV files, imports closing-rank rows, and predicts colleges based on estimated rank and filters.
- [services/__init__.py](services/__init__.py) is empty and exists only to mark the package.

## Frontend
- [templates/base.html](templates/base.html) defines the shared page shell, navigation, and chart library include.
- [templates/home.html](templates/home.html) provides the submission form for two response-sheet URLs.
- [templates/analysis.html](templates/analysis.html) shows total score, paper scores, section breakdown, and links to deeper views.
- [templates/questions.html](templates/questions.html) renders question-by-question analysis with filtering by paper and subject.
- [templates/rank.html](templates/rank.html) shows rank metrics, score distribution, and JoSAA predictor controls.
- [templates/admin/index.html](templates/admin/index.html) is the admin dashboard for data entry and maintenance.
- [static/app.js](static/app.js) powers the charts, tab filtering, question navigation, loading indicator, and JoSAA prediction table.
- [static/styles.css](static/styles.css) contains the full visual design system for the app.

## Tests
- [tests/test_routes.py](tests/test_routes.py) checks the home page, admin authentication protection, and 404 behavior for missing analyses.
- [tests/test_evaluator.py](tests/test_evaluator.py) validates scoring logic for correct, incorrect, unattempted, partial, and numeric-tolerance cases.
- [tests/test_parser.py](tests/test_parser.py) verifies parsing of sample DigiAlm response-sheet HTML fixtures.
- [tests/test_rank.py](tests/test_rank.py) checks rank estimation and percentile calculations from stored submissions.
- [tests/test_josaa.py](tests/test_josaa.py) checks JoSAA CSV import and prediction filtering.
- [tests/test_hash.py](tests/test_hash.py) ensures submission hashing is stable regardless of question order.
- [tests/fixtures/paper1_sample.html](tests/fixtures/paper1_sample.html) and [tests/fixtures/paper2_sample.html](tests/fixtures/paper2_sample.html) are parser fixtures.

## Notes
- The [data](data) directory is currently empty.
- The app is organized as a small FastAPI stack with async database access, HTML parsing for response sheets, scoring/evaluation services, and a lightweight browser UI.