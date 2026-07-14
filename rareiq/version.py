VERSION = "Studio X 6.3"
CODENAME = "Backend Test Foundation"
BUILD_DATE = "2026.07.13"
PRODUCT_NAME = "RareIQ"
PROJECT_NAME = "Project Digital Jazz"

def version_payload() -> dict[str, str]:
    return {
        "product": PRODUCT_NAME,
        "version": VERSION,
        "codename": CODENAME,
        "build_date": BUILD_DATE,
        "project": PROJECT_NAME,
    }
