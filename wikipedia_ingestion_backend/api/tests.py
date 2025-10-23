import io
import os
import unittest
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import IngestionJob, IngestionItem
from .exceptions import CSVFormatError, FetchError, Neo4jWriteError

# Ensure deterministic behavior for tests (force sync ingestion)
os.environ["USE_SYNC_INGEST"] = "true"


class HealthTests(APITestCase):
    def test_health(self):
        url = reverse("Health")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"message": "Server is up!"})


class CSVParserTests(TestCase):
    @mock.patch("api.services.csv_parser.csv")
    def test_parse_csv_basic_first_column(self, mock_csv):
        # prepare rows returned by csv.reader
        mock_csv.reader.return_value = [["header1", "header2"], ["val1", "x"], ["val2", "y"]]
        from api.services.csv_parser import parse_csv_content

        values = parse_csv_content(b"dummy-bytes", column_name=None, has_header=True, encoding="utf-8")
        self.assertEqual(values, ["val1", "val2"])
        # Ensure csv.reader was called
        self.assertTrue(mock_csv.reader.called)

    @mock.patch("api.services.csv_parser.csv")
    def test_parse_csv_with_column_name_missing_header_fallback(self, mock_csv):
        mock_csv.reader.return_value = [["name", "url"], ["A", "alink"], ["B", "blink"]]
        from api.services.csv_parser import parse_csv_content

        # Column name not present will fallback to first column
        values = parse_csv_content(b"dummy", column_name="missing", has_header=True)
        self.assertEqual(values, ["A", "B"])

    def test_parse_csv_decode_error(self):
        from api.services.csv_parser import parse_csv_content

        with self.assertRaises(CSVFormatError):
            # Use an invalid encoding scenario by passing bytes that can't decode with ascii and forcing encoding="ascii"
            parse_csv_content("ç".encode("utf-16"), has_header=False, encoding="ascii")

    def test_classify_source(self):
        from api.services.csv_parser import classify_source

        st, v = classify_source("https://en.wikipedia.org/wiki/Alan_Turing")
        self.assertEqual(st, "LINK")
        self.assertEqual(v, "https://en.wikipedia.org/wiki/Alan_Turing")

        st, v = classify_source("Alan Turing")
        self.assertEqual(st, "TOPIC")
        self.assertEqual(v, "Alan Turing")

        st, v = classify_source("https://example.com/page")
        self.assertEqual(st, "LINK")  # Non-wikipedia links are still LINK


class WikipediaClientTests(TestCase):
    @mock.patch("api.services.wikipedia_client._fetch_by_title")
    @mock.patch("api.services.wikipedia_client._search_and_fetch")
    def test_fetch_topic_success_via_title(self, mock_search, mock_title):
        from api.services.wikipedia_client import fetch_wikipedia, WikipediaPage

        mock_title.return_value = WikipediaPage(title="Alan Turing", url="http://w", text="content")
        page = fetch_wikipedia("Alan Turing")
        self.assertEqual(page.title, "Alan Turing")
        mock_title.assert_called_once()
        mock_search.assert_not_called()

    @mock.patch("api.services.wikipedia_client._fetch_by_title")
    @mock.patch("api.services.wikipedia_client._search_and_fetch")
    def test_fetch_topic_fallback_to_search(self, mock_search, mock_title):
        from api.services.wikipedia_client import fetch_wikipedia, WikipediaPage

        mock_title.return_value = None
        mock_search.return_value = WikipediaPage(title="Alan Turing", url="http://w", text="content")
        page = fetch_wikipedia("Alan Turing")
        self.assertEqual(page.title, "Alan Turing")
        mock_title.assert_called_once()
        mock_search.assert_called_once()

    @mock.patch("api.services.wikipedia_client._fetch_from_url")
    def test_fetch_url_success(self, mock_url):
        from api.services.wikipedia_client import fetch_wikipedia, WikipediaPage

        mock_url.return_value = WikipediaPage(title="T", url="u", text="t")
        page = fetch_wikipedia("https://en.wikipedia.org/wiki/Alan_Turing")
        self.assertEqual(page.url, "u")
        mock_url.assert_called()

    @mock.patch("api.services.wikipedia_client._fetch_by_title", return_value=None)
    @mock.patch("api.services.wikipedia_client._search_and_fetch", return_value=None)
    @mock.patch("api.services.wikipedia_client._fetch_from_url", return_value=None)
    def test_fetch_failure_raises(self, mock_u, mock_s, mock_t):
        from api.services.wikipedia_client import fetch_wikipedia

        with self.assertRaises(FetchError):
            fetch_wikipedia("Non Existent Topic", retries=1)


class ChunkingTests(TestCase):
    @mock.patch("api.services.chunking.RecursiveCharacterTextSplitter")
    def test_chunk_text_uses_langchain_splitter(self, mock_splitter_cls):
        from api.services.chunking import chunk_text

        splitter_instance = mock.Mock()
        splitter_instance.split_text.return_value = ["a", "b", "c"]
        mock_splitter_cls.return_value = splitter_instance

        chunks = chunk_text("abcdef", {"title": "T", "url": "U"})
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0]["metadata"]["chunk_index"], 0)
        self.assertEqual(chunks[1]["metadata"]["chunk_index"], 1)
        self.assertEqual(chunks[2]["metadata"]["chunk_index"], 2)
        mock_splitter_cls.assert_called_once()


class EmbeddingsTests(TestCase):
    @mock.patch("api.services.rag_pipeline._ensure_sentence_transformers")
    @mock.patch("api.services.rag_pipeline._sentence_model")
    def test_embed_texts_sentence_transformers(self, mock_model, mock_ensure):
        os.environ["EMBEDDINGS_PROVIDER"] = "sentence-transformers"
        from api.services.rag_pipeline import embed_texts

        # mock model.encode to return a numpy-like list
        mock_model.encode.return_value = [[0.1, 0.2], [0.3, 0.4]]
        vecs = embed_texts(["a", "b"])
        self.assertEqual(len(vecs), 2)
        self.assertEqual(vecs[0][0], 0.1)
        mock_ensure.assert_called_once()
        mock_model.encode.assert_called_once()

    @mock.patch("api.services.rag_pipeline._ensure_openai")
    @mock.patch("api.services.rag_pipeline._openai_client")
    def test_embed_texts_openai(self, mock_client, mock_ensure_openai):
        os.environ["EMBEDDINGS_PROVIDER"] = "openai"
        os.environ["OPENAI_API_KEY"] = "sk-test"
        from api.services.rag_pipeline import embed_texts

        # Mock OpenAI embeddings.create response
        class _D:
            def __init__(self, emb):
                self.embedding = emb

        class _R:
            def __init__(self, data):
                self.data = data

        mock_client.embeddings.create.return_value = _R([_D([1.0, 2.0]), _D([3.0, 4.0])])
        vecs = embed_texts(["x", "y"])
        self.assertEqual(vecs, [[1.0, 2.0], [3.0, 4.0]])
        mock_ensure_openai.assert_called_once()
        mock_client.embeddings.create.assert_called_once()

    def tearDown(self):
        # Reset provider to default for other tests
        os.environ["EMBEDDINGS_PROVIDER"] = "sentence-transformers"
        if "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]


class Neo4jWriterTests(TestCase):
    @mock.patch("api.services.neo4j_writer.GraphDatabase")
    def test_write_article_with_chunks_success(self, mock_graph):
        from api.services.neo4j_writer import Neo4jWriter

        # Mock driver and session context manager
        session_mock = mock.MagicMock()
        driver_mock = mock.MagicMock()
        driver_mock.session.return_value.__enter__.return_value = session_mock
        mock_graph.driver.return_value = driver_mock

        writer = Neo4jWriter(uri="bolt://localhost:7687", user="neo4j", password="pass")
        chunks = [{"text": "chunk1", "metadata": {"title": "T", "url": "U"}}, {"text": "chunk2", "metadata": {"title": "T", "url": "U"}}]
        emb = [[0.1, 0.2], [0.3, 0.4]]

        a, c = writer.write_article_with_chunks("T", "U", chunks, embeddings=emb, store_embeddings=True)
        self.assertEqual((a, c), (1, 2))
        # Ensure schema and runs were made
        self.assertTrue(session_mock.run.called)
        writer.close()

    @mock.patch("api.services.neo4j_writer.GraphDatabase")
    def test_write_article_with_chunks_driver_error(self, mock_graph):
        from api.services.neo4j_writer import Neo4jWriter

        mock_graph.driver.side_effect = Exception("boom")
        writer = Neo4jWriter(uri="bolt://x", user="u", password="p")
        with self.assertRaises(Neo4jWriteError):
            writer.write_article_with_chunks("T", "U", [])
        writer.close()


class OrchestratorTests(TestCase):
    @mock.patch("api.services.pipeline_orchestrator.Neo4jWriter")
    @mock.patch("api.services.pipeline_orchestrator.embed_texts")
    @mock.patch("api.services.pipeline_orchestrator.chunk_text")
    @mock.patch("api.services.pipeline_orchestrator.fetch_wikipedia")
    def test_run_job_pipeline_status_transitions_success(
        self, mock_fetch, mock_chunk, mock_embed, mock_writer_cls
    ):
        from api.services.pipeline_orchestrator import run_job_pipeline, OrchestratorResult
        from api.services.wikipedia_client import WikipediaPage

        job = IngestionJob.objects.create(status=IngestionJob.Status.PENDING, total_items=0, processed_items=0)
        item = IngestionItem.objects.create(
            job=job, input_value="Alan Turing", source_type=IngestionItem.SourceType.TOPIC, status=IngestionItem.Status.PENDING
        )

        # Mocks behavior
        mock_fetch.return_value = WikipediaPage(title="Alan Turing", url="http://u", text="some content")
        mock_chunk.return_value = [
            {"text": "c1", "metadata": {"title": "Alan Turing", "url": "http://u"}},
            {"text": "c2", "metadata": {"title": "Alan Turing", "url": "http://u"}},
        ]
        mock_embed.return_value = [[0.1], [0.2]]
        writer_inst = mock.MagicMock()
        mock_writer_cls.return_value = writer_inst

        result: OrchestratorResult = run_job_pipeline(job)
        job.refresh_from_db()
        item.refresh_from_db()

        self.assertEqual(result.total, 1)
        self.assertEqual(result.failed, 0)
        self.assertEqual(job.status, IngestionJob.Status.SUCCESS)
        self.assertEqual(item.status, IngestionItem.Status.SUCCESS)
        writer_inst.write_article_with_chunks.assert_called_once()

    @mock.patch("api.services.pipeline_orchestrator.Neo4jWriter")
    @mock.patch("api.services.pipeline_orchestrator.embed_texts")
    @mock.patch("api.services.pipeline_orchestrator.chunk_text")
    @mock.patch("api.services.pipeline_orchestrator.fetch_wikipedia")
    def test_run_job_pipeline_handles_fetch_error(
        self, mock_fetch, mock_chunk, mock_embed, mock_writer_cls
    ):
        from api.services.pipeline_orchestrator import run_job_pipeline

        job = IngestionJob.objects.create(status=IngestionJob.Status.PENDING, total_items=0, processed_items=0)
        item = IngestionItem.objects.create(
            job=job, input_value="Bad", source_type=IngestionItem.SourceType.TOPIC, status=IngestionItem.Status.PENDING
        )

        mock_fetch.side_effect = FetchError("nope")

        run_job_pipeline(job)
        job.refresh_from_db()
        item.refresh_from_db()

        self.assertEqual(job.status, IngestionJob.Status.FAILED)
        self.assertEqual(item.status, IngestionItem.Status.FAILED)
        mock_writer_cls.assert_called_once()

    @mock.patch("api.services.pipeline_orchestrator.Neo4jWriter")
    @mock.patch("api.services.pipeline_orchestrator.embed_texts", side_effect=Exception("embed failed"))
    @mock.patch("api.services.pipeline_orchestrator.chunk_text")
    @mock.patch("api.services.pipeline_orchestrator.fetch_wikipedia")
    def test_run_job_pipeline_embedding_error_continues(
        self, mock_fetch, mock_chunk, mock_embed, mock_writer_cls
    ):
        from api.services.pipeline_orchestrator import run_job_pipeline
        from api.services.wikipedia_client import WikipediaPage

        job = IngestionJob.objects.create(status=IngestionJob.Status.PENDING, total_items=0, processed_items=0)
        item = IngestionItem.objects.create(
            job=job, input_value="Alan", source_type=IngestionItem.SourceType.TOPIC, status=IngestionItem.Status.PENDING
        )

        mock_fetch.return_value = WikipediaPage(title="t", url="u", text="content")
        mock_chunk.return_value = [{"text": "c1", "metadata": {"title": "t", "url": "u"}}]
        writer_inst = mock.MagicMock()
        mock_writer_cls.return_value = writer_inst

        run_job_pipeline(job)
        job.refresh_from_db()
        item.refresh_from_db()

        # Even though embeddings failed, we should have succeeded and written without embeddings
        self.assertEqual(item.status, IngestionItem.Status.SUCCESS)
        writer_inst.write_article_with_chunks.assert_called_once()
        args, kwargs = writer_inst.write_article_with_chunks.call_args
        # embeddings should be None or store_embeddings False
        self.assertTrue(kwargs.get("embeddings") in (None, []))


class APITests(APITestCase):
    def setUp(self):
        # Deterministic synchronous ingestion
        os.environ["USE_SYNC_INGEST"] = "true"

    @mock.patch("api.views.submit_ingestion_job")
    @mock.patch("api.views.parse_csv_content")
    def test_upload_csv_valid_sync(self, mock_parse, mock_submit):
        # Force sync mode path in view by making submit_ingestion_job return (None, "sync")
        mock_submit.return_value = (None, "sync")
        mock_parse.return_value = ["Alan Turing", "Ada Lovelace"]

        url = reverse("ingest-upload-csv")
        csv_content = "topic\nAlan Turing\nAda Lovelace\n".encode("utf-8")
        data = {
            "csv_file": io.BytesIO(csv_content),
            "has_header": "true",
        }
        response = self.client.post(url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertIn("job_id", body)
        self.assertIn("counts", body)
        # Ensure models created
        job_id = body["job_id"]
        job = IngestionJob.objects.get(pk=job_id)
        self.assertEqual(job.total_items, 2)
        self.assertEqual(job.items.count(), 2)
        mock_parse.assert_called_once()
        mock_submit.assert_called_once()

    @mock.patch("api.views.parse_csv_content", side_effect=CSVFormatError("bad csv"))
    def test_upload_csv_invalid_csv(self, mock_parse):
        url = reverse("ingest-upload-csv")
        csv_content = b"bad,data"
        data = {
            "csv_file": io.BytesIO(csv_content),
            "has_header": "false",
        }
        response = self.client.post(url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertIn("error", body)

    def test_single_ingest_requires_value(self):
        url = reverse("ingest-single")
        resp = self.client.post(url, data={"value": ""}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(resp.json()["success"])

    @mock.patch("api.views.submit_ingestion_job", return_value=(None, "sync"))
    def test_single_ingest_sync_success(self, mock_submit):
        url = reverse("ingest-single")
        resp = self.client.post(url, data={"value": "Alan Turing"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertIn("job_id", body)
        job = IngestionJob.objects.get(pk=body["job_id"])
        self.assertEqual(job.total_items, 1)
        self.assertEqual(job.items.count(), 1)

    def test_job_status_and_items(self):
        # Create job and items
        job = IngestionJob.objects.create(status=IngestionJob.Status.PENDING, total_items=2, processed_items=1)
        IngestionItem.objects.create(job=job, input_value="A", source_type=IngestionItem.SourceType.TOPIC, status=IngestionItem.Status.SUCCESS)
        IngestionItem.objects.create(job=job, input_value="B", source_type=IngestionItem.SourceType.LINK, status=IngestionItem.Status.FAILED)

        status_url = reverse("ingest-job-status", kwargs={"job_id": job.pk})
        items_url = reverse("ingest-job-items", kwargs={"job_id": job.pk})

        s_resp = self.client.get(status_url)
        i_resp = self.client.get(items_url)

        self.assertEqual(s_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(i_resp.status_code, status.HTTP_200_OK)

        s_json = s_resp.json()
        i_json = i_resp.json()

        self.assertTrue(s_json["success"])
        self.assertEqual(s_json["job_id"], job.pk)
        self.assertIn("counts", s_json)
        self.assertEqual(s_json["counts"]["total"], 2)
        self.assertEqual(s_json["counts"]["succeeded"], 1)
        self.assertEqual(s_json["counts"]["failed"], 1)

        self.assertTrue(i_json["success"])
        self.assertIsInstance(i_json["detail"], list)
        self.assertEqual(len(i_json["detail"]), 2)


@unittest.skipUnless(
    all(os.environ.get(k) for k in ["NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"]),
    "Skipping smoke test without Neo4j env vars",
)
class OptionalNeo4jSmokeTest(TestCase):
    def test_env_present(self):
        # This test does not connect; just confirms env presence for CI visibility.
        self.assertTrue(os.environ.get("NEO4J_URI"))
        self.assertTrue(os.environ.get("NEO4J_USER"))
        self.assertTrue(os.environ.get("NEO4J_PASSWORD"))
