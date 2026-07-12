VERSION = "1.2.0"
CODENAME = "Command Center"
BUILD_DATE = "2026.07.11"
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
