from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem

HEADERS = ("Pos", "Driver", "Best lap", "Race time", "Gap", "Laps", "Result", "Car")


class ResultItem(QTableWidgetItem):
    def __init__(self, text, value, entry):
        super().__init__(text)
        self.value = value
        self.setData(Qt.UserRole, entry)

    def __lt__(self, other):
        if not isinstance(other, ResultItem):
            return super().__lt__(other)
        descending = (
            self.tableWidget()
            and self.tableWidget().horizontalHeader().sortIndicatorOrder() == Qt.DescendingOrder
        )
        if self.value is None:
            return other.value is not None and bool(descending)
        if other.value is None:
            return not descending
        return self.value < other.value


def result_values(entry, leader_time, lap=None):
    position = entry.get("position")
    name = entry.get("name", "Unknown driver")
    best = entry.get("best_lap_ms")
    race = entry.get("total_time_ms")
    gap = race - leader_time if race is not None and leader_time is not None else None
    status = "Finished" if position is not None and race is not None else "Unclassified"
    car = entry.get("car_name") or (
        "Car #" + str(entry["car_code"]) if entry.get("car_code") is not None else None
    )
    return position, name, best, race, gap, lap, status, car
