"""Automation script for ordering robots."""

from __future__ import annotations

import os
import re
import shutil
import textwrap
from dataclasses import dataclass
from pathlib import Path

from RPA.HTTP import HTTP
from RPA.Tables import Tables
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from robocorp import browser, log
from robocorp.tasks import task


log.setup_log(
    max_value_repr_size="200k",
    output_log_level="info",
)
logger = log.get_logger(__name__)

# URLs used by the automation
ORDER_URL = "https://robotsparebinindustries.com/#/robot-order"
ORDERS_CSV_URL = "https://robotsparebinindustries.com/orders.csv"

# File system paths
OUTPUT_DIR = Path("output")
DATA_DIR = OUTPUT_DIR / "data"
SCREENSHOTS_DIR = OUTPUT_DIR / "screenshots"
RECEIPTS_DIR = OUTPUT_DIR / "receipts"


@dataclass
class RobotOrder:
    """
    Represents a robot order with its attributes.
    """

    order_number: str
    head: str
    body: str
    legs: str
    address: str


def configure_browser() -> None:
    """Set default configuration for the Robocorp browser."""
    browser.configure(slowmo=100)


@task
def order_robots_from_robot_spare_bin() -> None:
    """
    Orders robots from RobotSpareBin Industries Inc.
    Saves the order HTML receipt as a PDF file.
    Saves the screenshot of the ordered robot.
    Embeds the screenshot of the robot to the PDF receipt.
    Creates ZIP archive of the receipts and the images.
    """

    configure_browser()
    clean_screenshots_dir()
    clean_receipts_dir()
    open_robot_order_website()
    download_orders_csv_file()
    fill_form_with_csv_data()


def clean_screenshots_dir(dir_path: Path = SCREENSHOTS_DIR) -> None:
    """Remove the screenshot directory if it exists."""
    if dir_path.is_dir():
        shutil.rmtree(dir_path)


def clean_receipts_dir(dir_path: Path = RECEIPTS_DIR) -> None:
    """Remove the receipts directory if it exists."""
    if dir_path.is_dir():
        shutil.rmtree(dir_path)


def download_orders_csv_file() -> None:
    """Download the order CSV file from the service."""
    http = HTTP()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    http.download(url=ORDERS_CSV_URL, overwrite=True, target_file=str(DATA_DIR / "orders.csv"))


def open_robot_order_website() -> None:
    """Navigate to the robot order page."""
    browser.goto(ORDER_URL)
    logger.info("Robot Spare Bin Industries Inc. website opened.")


def fill_and_submit_order_form(robot_order: RobotOrder, attempts: int = 3) -> None:
    """Fill the order form with the given data and submit it."""
    page = browser.page()
    page.wait_for_selector("button:text('OK')", timeout=10000)
    page.click("button:text('OK')")

    logger.info("Filling the robot order form...")
    for attempt in range(1, attempts + 1):
        page.wait_for_selector("#head", timeout=10000)
        page.query_selector("#head").select_option(robot_order.head)

        body_locator = f"css=input[name='body'][value='{robot_order.body}']"
        page.check(body_locator)

        page.fill("input[placeholder='Enter the part number for the legs']", robot_order.legs)
        page.fill("#address", robot_order.address)

        page.click("#order")
        page.wait_for_timeout(1000)

        if not page.locator("div[class='alert alert-danger'][role='alert']").is_visible():
            return

        logger.warning("Order submission failed for %s. Retrying (%s/%s)...", robot_order, attempt, attempts)
        page.reload()

    raise RuntimeError(f"Failed to submit order for {robot_order.order_number} after {attempts} attempts")


def order_another_robot() -> None:
    """Trigger ordering of another robot."""
    page = browser.page()
    page.wait_for_selector("button:text('ORDER ANOTHER ROBOT')", timeout=10000)
    page.click("button:text('ORDER ANOTHER ROBOT')")


def save_robot_screenshot(robot_order: RobotOrder) -> Path:
    """Save a screenshot of the ordered robot."""
    page = browser.page()
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    screenshot_path = SCREENSHOTS_DIR / f"robot_{robot_order.order_number}.png"

    page.wait_for_selector("#robot-preview-image", timeout=10000)
    page.query_selector("#robot-preview-image").screenshot(path=str(screenshot_path))
    logger.info("Robot screenshot saved at: %s", screenshot_path)
    return screenshot_path


def write_receipt_to_pdf(
    order_id: str,
    order_timestamp: str,
    order_html: str,
    screenshot_path: Path,
    order_address: str,
) -> Path:
    """Create a PDF receipt for the robot order."""
    pdf_path = RECEIPTS_DIR / f"receipt_{order_id}.pdf"
    logger.info("Saving receipt to PDF: %s", pdf_path)

    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(pdf_path, pagesize=A4)
    page_width, page_height = A4

    # Define starting Y coordinate (50 pts down from top)
    top_margin = 50
    current_y = page_height - top_margin

    # Draw “Receipt” in red, bold, 18pt
    c.setFillColor(colors.red)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, current_y, "Receipt")

    line_height = 18
    current_y -= line_height

    c.setFillColor(colors.black)
    c.setFont("Helvetica", 12)
    c.drawString(50, current_y, order_timestamp)

    current_y -= line_height

    c.drawString(50, current_y, order_id)

    current_y -= line_height

    clean_order_html = re.sub(r"</?div[^>]*>", "", order_html).strip()
    c.drawString(50, current_y, f"{order_address}{clean_order_html}")

    current_y -= line_height

    thank_you_text = (
        "Thank you for your order! We will ship your robot to you as soon as "
        "our warehouse robots gather the parts you ordered! You will receive your robot in no time!"
    )
    wrapped_lines = textwrap.wrap(thank_you_text, width=100)
    for line in wrapped_lines:
        if current_y < 100:
            break
        c.drawString(50, current_y, line)
        current_y -= line_height

    img = ImageReader(str(screenshot_path))
    img_width, img_height = img.getSize()

    max_img_width = page_width * 0.8
    max_img_height = page_height * 0.4

    scale = min(max_img_width / img_width, max_img_height / img_height, 1.0)
    img_width *= scale
    img_height *= scale

    bottom_padding = 20
    img_y = current_y - img_height - bottom_padding
    if img_y < 50:
        img_y = 50

    img_x = (page_width - img_width) / 2
    c.drawImage(img, img_x, img_y, width=img_width, height=img_height)

    c.save()
    logger.info("Receipt PDF saved successfully.")
    return pdf_path


def generate_robot_order_receipt(screenshot_path: Path) -> Path:
    """Parse receipt data from the page and create a PDF."""
    page = browser.page()
    receipt_data = page.query_selector("#receipt")
    order_id = receipt_data.query_selector("p[class='badge badge-success']").text_content()
    order_timestamp = receipt_data.query_selector("div:nth-child(2)").text_content()
    parts_html = receipt_data.query_selector("#parts").inner_html()
    order_address = receipt_data.query_selector("p:nth-child(4)").text_content()

    return write_receipt_to_pdf(order_id, order_timestamp, parts_html, screenshot_path, order_address)


def fill_form_with_csv_data() -> None:
    """Read the CSV orders and process each order."""
    table = Tables()
    csv_path = DATA_DIR / "orders.csv"
    rows = table.read_table_from_csv(str(csv_path), delimiters=",", header=True)
    logger.info("CSV data loaded from orders.csv: %s", rows)

    for row in rows:
        logger.info("Processing row: %s", row)
        robot_order = RobotOrder(
            order_number=row.get("Order number"),
            head=row.get("Head"),
            body=row.get("Body"),
            legs=row.get("Legs"),
            address=row.get("Address"),
        )
        logger.info("Filling the order form with data: %s", robot_order)
        fill_and_submit_order_form(robot_order)
        screenshot = save_robot_screenshot(robot_order)
        generate_robot_order_receipt(screenshot_path=screenshot)
        order_another_robot()

