import asyncio

from playwright.async_api import async_playwright


URL = (
    "https://fieldfisher.current-vacancies.com/"
    "Careers/Fieldfisher%20Vacancy%20Search%20Page-2074"
)


async def main() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in {"image", "font", "media"}
                else route.continue_(),
            )
            request_seen = asyncio.Event()

            async def capture_request(request) -> None:
                if request.url.endswith("/Careers/SearchVacancies"):
                    print("HEADERS", request.headers)
                    print("POST_DATA", request.post_data)
                    request_seen.set()

            page.on("request", capture_request)
            await page.goto(URL, wait_until="commit", timeout=60_000)
            await page.wait_for_function(
                "typeof performSearch === 'function' && "
                "document.querySelector('#searchbtn')",
                timeout=60_000,
            )
            async with page.expect_response(
                lambda response: response.url.endswith("/Careers/SearchVacancies"),
                timeout=60_000,
            ) as response_info:
                await page.evaluate("performSearch()")

            response = await response_info.value
            request = response.request
            print("STATUS", response.status)
            print("RESPONSE", await response.text())
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
