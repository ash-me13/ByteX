from models.schemas import HealthResponse

class HealthService:
    @staticmethod
    def get_health() -> HealthResponse:
        return HealthResponse(
            status="online",
            assistant="ByteX",
            version="0.1.0"
        )
