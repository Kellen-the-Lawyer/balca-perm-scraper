from balca_perm_scraper.parser import parse_search_results

SAMPLE_HTML = """
<html>
  <body>
    <article class="search-result">
      <h2><a href="/case/123">Acme Corp., 2024-PER-00123</a></h2>
      <p>Decision issued Jan. 4, 2025</p>
      <a href="/docs/acme.pdf">PDF</a>
    </article>
  </body>
</html>
"""


def test_parse_search_results():
    records = parse_search_results(SAMPLE_HTML)
    assert len(records) == 1
    assert records[0].docket_number == "2024-PER-00123"
    assert str(records[0].pdf_url).endswith("/docs/acme.pdf")
