import os
import logging
import unittest
from datetime import datetime as dt

import pandas as pd
from dotenv import load_dotenv

from score import *
from src.main import *
from src.QA_integration import QA_RAG
from src.entities.source_node import sourceNode

load_dotenv()

URI = os.getenv("NEO4J_URI")
USERNAME = os.getenv("NEO4J_USERNAME")
PASSWORD = os.getenv("NEO4J_PASSWORD")
DATABASE = os.getenv("NEO4J_DATABASE")

NEO4J_CONFIG_COMPLETE = all([URI, USERNAME, PASSWORD, DATABASE])

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def get_graph():
    """Lazy Neo4j connection to avoid side effects on import."""
    return create_graph_database_connection(
        URI,
        USERNAME,
        PASSWORD,
        DATABASE,
    )


def create_source_node_local(graph, model, file_name):
    source_node = sourceNode()
    source_node.file_name = file_name
    source_node.file_type = "pdf"
    source_node.file_size = "1087"
    source_node.file_source = "local file"
    source_node.model = model
    source_node.created_at = dt.now()

    graphDB_data_Access = graphDBdataAccess(graph)
    graphDB_data_Access.create_source_node(source_node)
    return source_node


# @unittest.skipUnless(NEO4J_CONFIG_COMPLETE, "Skipping: Neo4j env vars not fully configured")
class TestCommunitiesQA(unittest.TestCase):
    """
    Lightweight integration tests to validate that QA_RAG works against Neo4j.
    Heavy multi-model loops tetap dijalankan manual via run_tests() kalau perlu.
    """

    @classmethod
    def setUpClass(cls):
        cls.graph = get_graph()
        cls.model_name = os.getenv("TEST_COMMUNITIES_MODEL", "openai_gpt_4o")

    def test_chatbot_qna_entity_vector(self):
        """Basic sanity check: QA_RAG returns non-trivial answer."""
        result = QA_RAG(
            self.graph,
            self.model_name,
            "Tell me about Amazon",
            "[]",
            1,
            "entity search+vector",
        )

        self.assertIsInstance(result, dict)
        self.assertIn("message", result)
        self.assertGreater(len(result["message"]), 20)


# ==== ORIGINAL BULK RUNNER (optional manual run) ======================

def run_tests():
    """
    Original multi-model runner.
    Tidak dipanggil oleh unittest discovery.
    Jalankan manual:
        python test_commutiesqa.py
    """
    from pathlib import Path

    final_list = []
    error_list = []

    models = [
        "openai-gpt-3.5",
        "openai-gpt-4o",
        "openai-gpt-4o-mini",
        "gemini-1.5-pro",
        "azure_ai_gpt_35",
        "azure_ai_gpt_4o",
        "ollama_llama3",
        "groq_llama3_70b",
        "anthropic_claude_3_5_sonnet",
        "fireworks_v3p1_405b",
        "bedrock_claude_3_5_sonnet",
    ]

    graph = get_graph()

    for model_name in models:
        try:
            res = QA_RAG(
                graph,
                model_name,
                "Tell me about amazon",
                "[]",
                1,
                "entity search+vector",
            )
            final_list.append({"model": model_name, "result": res})
        except Exception as e:
            logging.error(f"Error for model {model_name}: {e}")
            error_list.append((model_name, str(e)))

    df = pd.DataFrame(final_list)
    df["execution_date"] = dt.today().strftime("%Y-%m-%d")

    out = Path(".") / f"Integration_TestResult_{dt.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(out, index=False)

    if error_list:
        df_err = pd.DataFrame(error_list, columns=["Model", "Error"])
        df_err["execution_date"] = dt.today().strftime("%Y-%m-%d")
        out_err = Path(".") / f"Error_details_{dt.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df_err.to_csv(out_err, index=False)


if __name__ == "__main__":
    run_tests()
