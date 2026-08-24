VERSION = "6.4.17-dev"
CODENAME = "WAR Build Foundation"
BUILD_DATE = "2026.08.23"
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
