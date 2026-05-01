import math


class DriftCorrector:
    def __init__(self, alpha=0.02):
        self.alpha = alpha
        self.origin = None
        self.offset_x = 0.0
        self.offset_y = 0.0

    def update(self, odom_x_m, odom_y_m, gps_lat, gps_lon, gps_fix):
        gps_local = None
        if gps_fix and gps_lat and gps_lon:
            if self.origin is None:
                self.origin = (gps_lat, gps_lon)
            gps_local = self._latlon_to_local(gps_lat, gps_lon)
            target_offset_x = gps_local[0] - odom_x_m
            target_offset_y = gps_local[1] - odom_y_m
            self.offset_x = (1.0 - self.alpha) * self.offset_x + self.alpha * target_offset_x
            self.offset_y = (1.0 - self.alpha) * self.offset_y + self.alpha * target_offset_y

        corrected_x = odom_x_m + self.offset_x
        corrected_y = odom_y_m + self.offset_y
        return corrected_x, corrected_y, gps_local

    def _latlon_to_local(self, lat, lon):
        lat0, lon0 = self.origin
        r = 6371000.0
        dlat = math.radians(lat - lat0)
        dlon = math.radians(lon - lon0)
        x = r * dlon * math.cos(math.radians(lat0))
        y = r * dlat
        return x, y
