"""Central LLM service factory for the DB Designer Agent."""
from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()


def get_chat_llm(temperature: float = 0.0):
    """Return a LangChain AzureChatOpenAI instance."""
    from langchain_openai import AzureChatOpenAI

    return AzureChatOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1-mini"),
        temperature=temperature,
    )


def get_embeddings():
    """Return an AzureOpenAIEmbeddings instance."""
    from langchain_openai import AzureOpenAIEmbeddings

    return AzureOpenAIEmbeddings(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        azure_deployment=os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"),
    )
