import os
import json
import asyncio
import logging
import unittest
from datetime import datetime as dt
from pathlib import Path
import inspect

import pandas as pd
from dotenv import load_dotenv

from src.main import *
from src.QA_integration import QA_RAG

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

BASE_DIR = os.path.dirname(__file__)
MERGED_DIR = os.path.join(BASE_DIR, "merged_files")
TEST_RESULTS_DIR = os.path.join(BASE_DIR, "test_results")
os.makedirs(TEST_RESULTS_DIR, exist_ok=True)


def get_graph():
    return create_graph_database_connection(
        URI,
        USERNAME,
        PASSWORD,
        DATABASE,
    )


# @unittest.skipUnless(NEO4J_CONFIG_COMPLETE, "Skipping: Neo4j env vars not fully configured")
class TestIntegrationQA(unittest.TestCase):
    """
    Slim integration checks (1–2 happy paths).
    Full matrix tetap pakai run_tests() manual.
    """

    @classmethod
    def setUpClass(cls):
        cls.graph = get_graph()
        cls.model_name = os.getenv("TEST_INTEGRATION_MODEL", "openai_gpt_4o")

    def test_chatbot_vector_mode(self):
        res = QA_RAG(
            self.graph,
            self.model_name,
            "Tell me about Amazon",
            "[]",
            1,
            "vector",
        )
        self.assertIsInstance(res, dict)
        self.assertIn("message", res)
        self.assertGreater(len(res["message"]), 20)

    def test_populate_graph_schema_from_text(self):
        """
        Sanity check: fungsi populate_graph_schema_from_text bisa dipanggil
        dengan signature (text, model, is_schema_description_checked, is_local_storage).
        """
        schema_text = (
            "Amazon was founded on July 5, 1994, by Jeff Bezos in Bellevue, Washington."
        )

        result = populate_graph_schema_from_text(
            schema_text,
            self.model_name,  # model
            True,             # is_schema_description_checked
            True,             # is_local_storage (atau False, sesuai cara kamu pakai)
        )

        self.assertIsNotNone(result)
        

# ========= MANUAL FULL INTEGRATION RUNNER ===============================

def run_tests():
    extract_list = []
    extract_error_list = []
    chatbot_list = []
    chatbot_error_list = []
    other_api_list = []

    models = [
        "openai_gpt_4o",
        "openai_gpt_4o_mini",
        "openai_gpt_4.1",
        "openai_gpt_4.1_mini",
        "gemini_2.0_flash",
        "fireworks_llama4_maverick",
        "bedrock_nova_pro_v1",
    ]

    chatbot_modes = [
        "vector",
        "graph+vector",
        "fulltext",
        "graph+vector+fulltext",
        "entity search+vector",
    ]

    for model_name in models:
        logging.info(f"Starting tests for model: {model_name}")

        # --- contoh 1: chatbot semua mode ---
        for mode in chatbot_modes:
            try:
                graph = get_graph()
                result = QA_RAG(graph, model_name, "Tell me about Amazon", "[]", 1, mode)
                if isinstance(result, dict) and result.get("status") == "Failed":
                    chatbot_error_list.append(
                        (model_name, f"test_chatbot_qna ({mode})", result.get("error", "Unknown error"))
                    )
                else:
                    chatbot_list.append(
                        {"model": model_name, "mode": mode, "result": result}
                    )
            except Exception as e:
                logging.error(f"Error in test_chatbot_qna ({mode}) for {model_name}: {e}")
                chatbot_error_list.append(
                    (model_name, f"test_chatbot_qna ({mode})", str(e))
                )

        # --- contoh 2: schema from text ---
        try:
            schema_result = populate_graph_schema_from_text(
                "Amazon was founded on July 5, 1994, by Jeff Bezos in Bellevue, Washington.",
                model_name,
                True,
            )
            other_api_list.append({model_name: schema_result})
        except Exception as e:
            logging.error(
                f"Error in test_populate_graph_schema_from_text for {model_name}: {e}"
            )
            other_api_list.append({model_name: str(e)})

    # Save chatbot results
    if chatbot_list:
        df_chatbot = pd.DataFrame(chatbot_list)
        df_chatbot["execution_date"] = dt.today().strftime("%Y-%m-%d")
        df_chatbot.to_csv(
            Path(TEST_RESULTS_DIR)
            / f"chatbot_Integration_TestResult_{dt.now().strftime('%Y%m%d_%H%M%S')}.csv",
            index=False,
        )

    # Save errors
    if chatbot_error_list:
        df_errors = pd.DataFrame(
            chatbot_error_list, columns=["Model", "Function", "Error"]
        )
        df_errors["execution_date"] = dt.today().strftime("%Y-%m-%d")
        df_errors.to_csv(
            Path(TEST_RESULTS_DIR)
            / f"chatbot_Error_details_{dt.now().strftime('%Y%m%d_%H%M%S')}.csv",
            index=False,
        )

    # Save other API results
    other_api_dict = {
        "test_populate_graph_schema_from_text": other_api_list,
    }
    with open(
        Path(TEST_RESULTS_DIR)
        / f"other_api_results_{dt.now().strftime('%Y%m%d_%H%M%S')}.json",
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(other_api_dict, file, indent=4)

    logging.info("All manual integration tests completed.")


if __name__ == "__main__":
    if not NEO4J_CONFIG_COMPLETE:
        print("Neo4j environment is not fully configured. Aborting integration run.")
    else:
        run_tests()
