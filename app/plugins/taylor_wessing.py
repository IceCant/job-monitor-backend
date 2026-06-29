from app.plugins.successfactors import SuccessFactorsPlugin


class TaylorWessingPlugin(SuccessFactorsPlugin):
    plugin_name = "taylor_wessing"
    display_name = "Taylor Wessing"
    discoverable = True
    enabled = True
    careers_url = (
        "https://careers.winstontaylor-emea.com/Careeropportunities/"
        "go/Career-opportunities/9053755/"
    )
    description = "Taylor Wessing / Winston Taylor EMEA SuccessFactors careers scraper"
    source_name = "taylor_wessing_successfactors_html"
    listing_style = "table"
    page_mode = "path"
    page_size = 15
    default_config = {
        "source_url": careers_url,
        "max_pages": 0,
        "safety_max_pages": 20,
        "fetch_detail_pages": True,
        "timeout": 60,
    }
