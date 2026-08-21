from __future__ import annotations

from .models import CandidateRoute


def attach_score_placeholder(route: CandidateRoute) -> CandidateRoute:
    route.future_score = None
    route.score_note = "后续评分入口：当前阶段只展示路线标签，暂不计算 PM2.5、噪声、花粉或综合暴露评分。"
    return route
