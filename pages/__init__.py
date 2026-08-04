# pages 页面对象包

from pages.base_page import BasePage
from pages.login_page import LoginPage
from pages.home_page import HomePage
from pages.case_list_page import CaseListPage
from pages.add_case_page import AddCasePage
from pages.customer_list_page import CustomerListPage
from pages.settings_page import SettingsPage
from pages.academy_page import AcademyPage
from pages.public_case_library_page import PublicCaseLibraryPage
from pages.customer_detail_page import CustomerDetailPage
from pages.watermark_settings_page import WatermarkSettingsPage
from pages.personal_center_page import PersonalCenterPage
from pages.recently_deleted_page import RecentlyDeletedPage
from pages.cloud_storage_page import CloudStoragePage

__all__ = [
    "BasePage",
    "LoginPage",
    "HomePage",
    "CaseListPage",
    "AddCasePage",
    "CustomerListPage",
    "SettingsPage",
    "AcademyPage",
    "PublicCaseLibraryPage",
    "CustomerDetailPage",
    "WatermarkSettingsPage",
    "PersonalCenterPage",
    "RecentlyDeletedPage",
    "CloudStoragePage",
]
