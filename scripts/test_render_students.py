from jinja2 import Environment, FileSystemLoader
from types import SimpleNamespace
from datetime import datetime

env = Environment(loader=FileSystemLoader('templates'))
template = env.get_template('admin/students.html')

row = SimpleNamespace(
    id=1,
    is_deleted=False,
    candidate_id='R001',
    candidate_name='Test Student',
    created_at=datetime.now(),
    paper_scores={'paper_1':12.5,'paper_2':8.0},
    total_score=20.5,
)

filters = SimpleNamespace(roll='', name='', min_score='', max_score='', date_from='', date_to='', include_deleted=False)

html = template.render(
    students=[row],
    filters=filters,
    page=1,
    per_page=25,
    total_pages=1,
    total_shown=1,
    active_count=1,
    deleted_count=0,
    pagination_qs=lambda p: '',
    error='',
    info='',
)

print('ok', len(html))
