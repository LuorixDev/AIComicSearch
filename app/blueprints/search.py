from flask import Blueprint, render_template, request
from ..models import search_comics

search_bp = Blueprint('search', __name__)

@search_bp.route('/search')
def search():
    """搜索结果路由。根据查询参数执行语义搜索并显示结果。"""
    query = request.args.get('query', '')
    results = []
    if query:
        results = search_comics(query)
    return render_template('search.html', query=query, results=results)
