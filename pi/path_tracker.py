import math
from dataclasses import dataclass


@dataclass
class PathPoint:
    x: float
    y: float
    heading: float
    timestamp_ms: int


class PathTracker:
    def __init__(self, min_step_m=0.05, min_time_ms=400, max_points=4000):
        self.min_step_m = min_step_m
        self.min_time_ms = min_time_ms
        self.max_points = max_points
        self.points = []
        self.last_point = None

    def update(self, x_m, y_m, heading_deg, timestamp_ms):
        if self.last_point is None:
            point = PathPoint(x_m, y_m, heading_deg, timestamp_ms)
            self.points.append(point)
            self.last_point = point
            return True

        dx = x_m - self.last_point.x
        dy = y_m - self.last_point.y
        dist = math.hypot(dx, dy)
        dt = timestamp_ms - self.last_point.timestamp_ms

        if dist >= self.min_step_m or dt >= self.min_time_ms:
            point = PathPoint(x_m, y_m, heading_deg, timestamp_ms)
            self.points.append(point)
            if len(self.points) > self.max_points:
                self.points = self.points[-self.max_points :]
            self.last_point = point
            return True

        return False

    def get_path(self):
        return [p.__dict__ for p in self.points]
