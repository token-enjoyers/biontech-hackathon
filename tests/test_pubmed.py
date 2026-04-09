from __future__ import annotations

import httpx
import pytest

from Medical_Wizard_MCP.sources.pubmed import BASE_URL, PubMedSource


PUBMED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>123</PMID>
      <Article>
        <ArticleTitle>mRNA cancer vaccine study</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">Promising early data.</AbstractText>
          <AbstractText>Expanded cohort showed durable response.</AbstractText>
        </Abstract>
        <Journal>
          <JournalIssue>
            <PubDate>
              <Year>2024</Year>
              <Month>Sep</Month>
              <Day>12</Day>
            </PubDate>
          </JournalIssue>
          <Title>Nature Medicine</Title>
        </Journal>
        <AuthorList>
          <Author>
            <ForeName>Alice</ForeName>
            <LastName>Smith</LastName>
          </Author>
          <Author>
            <CollectiveName>BioNTech Study Group</CollectiveName>
          </Author>
        </AuthorList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>456</PMID>
      <Article>
        <ArticleTitle>Second article</ArticleTitle>
        <Journal>
          <JournalIssue>
            <PubDate>
              <Year>2023</Year>
            </PubDate>
          </JournalIssue>
          <ISOAbbreviation>J Clin Oncol</ISOAbbreviation>
        </Journal>
        <AuthorList>
          <Author>
            <Initials>BB</Initials>
            <LastName>Jones</LastName>
          </Author>
        </AuthorList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


@pytest.mark.asyncio
async def test_search_publications_two_step_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, str]]] = []
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))

        if request.url.path.endswith("/esearch.fcgi"):
            assert request.url.params["db"] == "pubmed"
            assert request.url.params["term"] == "mrna vaccine"
            assert request.url.params["retmax"] == "2"
            assert request.url.params["retmode"] == "json"
            assert request.url.params["sort"] == "relevance"
            assert request.url.params["mindate"] == "2022/01/01"
            assert request.url.params["datetype"] == "pdat"
            return httpx.Response(
                200,
                json={"esearchresult": {"idlist": ["123", "456"]}},
            )

        if request.url.path.endswith("/efetch.fcgi"):
            assert request.url.params["db"] == "pubmed"
            assert request.url.params["id"] == "123,456"
            assert request.url.params["retmode"] == "xml"
            return httpx.Response(200, text=PUBMED_XML)

        raise AssertionError(f"Unexpected path: {request.url.path}")

    source = PubMedSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    source._api_key = None
    source._email = "test@example.com"
    monkeypatch.setattr("Medical_Wizard_MCP.sources.pubmed.asyncio.sleep", fake_sleep)

    results = await source.search_publications(
        "mrna vaccine",
        max_results=2,
        year_from=2022,
    )

    await source.close()

    assert sleep_calls == [0.4]
    assert [call[0] for call in calls] == ["/esearch.fcgi", "/efetch.fcgi"]
    assert [publication.pmid for publication in results] == ["123", "456"]
    assert results[0].journal == "Nature Medicine"
    assert results[0].pub_date == "2024-09-12"
    assert results[0].authors == ["Alice Smith", "BioNTech Study Group"]
    assert (
        results[0].abstract
        == "BACKGROUND: Promising early data.\n\nExpanded cohort showed durable response."
    )
    assert results[1].journal == "J Clin Oncol"
    assert results[1].pub_date == "2023"
    assert results[1].authors == ["BB Jones"]


@pytest.mark.asyncio
async def test_search_publications_returns_empty_list_when_esearch_has_no_results() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"esearchresult": {"idlist": []}})

    source = PubMedSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    source._api_key = None
    source._email = "test@example.com"

    results = await source.search_publications("no hits", max_results=5)

    await source.close()

    assert results == []
    assert calls == ["/esearch.fcgi"]


@pytest.mark.asyncio
async def test_search_publications_raises_clear_error_on_esearch_http_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    source = PubMedSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    source._api_key = None
    source._email = "test@example.com"

    with pytest.raises(RuntimeError, match="PubMed esearch failed with status 503"):
        await source.search_publications("mrna vaccine")

    await source.close()


@pytest.mark.asyncio
async def test_search_publications_raises_clear_error_on_invalid_efetch_xml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(_: float) -> None:
        return None

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["123"]}})
        return httpx.Response(200, text="<not-xml")

    source = PubMedSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    source._api_key = None
    source._email = "test@example.com"
    monkeypatch.setattr("Medical_Wizard_MCP.sources.pubmed.asyncio.sleep", fake_sleep)

    with pytest.raises(RuntimeError, match="PubMed efetch returned invalid XML"):
        await source.search_publications("mrna vaccine")

    await source.close()
