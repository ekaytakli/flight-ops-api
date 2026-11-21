from rest_framework.exceptions import APIException


class FlightDeletionConflict(APIException):
    status_code = 409
    default_detail = "Flights with incidents cannot be deleted."
    default_code = "flight_has_incidents"
