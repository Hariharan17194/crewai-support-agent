import hashlib
from pathlib import Path

from crewai import LLM, Agent, Crew, Process, Task
from crewai.tools import tool
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

DATA_DIR = Path("data")
INDEX_DIR = Path("faiss_index")
DATA_DIR.mkdir(exist_ok=True)

llm = LLM(model="gpt-4o-mini")


# ---------------------------------------------------------------------------
# RAG — build (or load a cached) FAISS index from an uploaded .txt file
# ---------------------------------------------------------------------------
def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_vector_db(txt_path: Path) -> FAISS:
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    index_subdir = INDEX_DIR / txt_path.stem
    hash_marker = index_subdir / "source.hash"
    current_hash = _file_hash(txt_path)

    if hash_marker.exists() and hash_marker.read_text() == current_hash:
        return FAISS.load_local(
            str(index_subdir),
            embeddings,
            allow_dangerous_deserialization=True,
        )

    docs = TextLoader(str(txt_path), encoding="utf-8").load()

    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150)
    chunks = splitter.split_documents(docs)

    vector_db = FAISS.from_documents(chunks, embeddings)

    index_subdir.mkdir(parents=True, exist_ok=True)
    vector_db.save_local(str(index_subdir))
    hash_marker.write_text(current_hash)

    return vector_db


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
def make_kb_tool(vector_db):
    @tool("Customer Support Knowledge Base")
    def customer_support_rag_tool(query: str) -> str:
        """
        Search the uploaded customer support document for policies on
        refunds, returns, shipping, orders, accounts, and payments.
        """
        if vector_db is None:
            return "Knowledge base is empty. No document has been uploaded."

        results = vector_db.similarity_search(query, k=4)
        if not results:
            return "No relevant information found in the knowledge base."

        return "\n\n".join(doc.page_content for doc in results)

    return customer_support_rag_tool


@tool("Web Search")
def web_search_tool(query: str) -> str:
    """
    Search the public web for up-to-date information related to the
    customer's question.
    """
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=5))

    if not results:
        return "No web results found."

    return "\n\n".join(f"{r['title']}\n{r['body']}\nSource: {r['href']}" for r in results)


# ---------------------------------------------------------------------------
# Single agent (knowledge base first, web as fallback) — used by the CLI
# ---------------------------------------------------------------------------
def build_single_agent(vector_db) -> Agent:
    return Agent(
        role="Customer Support Agent",
        goal=(
            "Answer customer queries accurately, using the knowledge base "
            "first and the web only as a fallback."
        ),
        backstory=(
            "You are a helpful customer support agent. You ALWAYS check the "
            "Customer Support Knowledge Base tool first. Only if it does not "
            "contain the answer, use the Web Search tool. Never invent "
            "information that isn't backed by a tool result. If neither tool "
            "has the answer, politely say you don't have enough information "
            "and suggest contacting support."
        ),
        tools=[make_kb_tool(vector_db), web_search_tool],
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )


def answer_single(query: str, vector_db) -> str:
    agent = build_single_agent(vector_db)
    task = Task(
        description=f"""
        Customer asked:

        {query}

        Step 1: Search the Customer Support Knowledge Base tool.
        Step 2: Only if the knowledge base doesn't have enough information,
        search the web for the answer.
        Step 3: Give a clear, friendly, professional customer support answer.
        Do not hallucinate.
        """,
        expected_output="A helpful customer support response.",
        agent=agent,
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
    return str(crew.kickoff())


# ---------------------------------------------------------------------------
# Dual agents (one strictly on the knowledge base, one strictly on the web)
# — used by the Streamlit UI so both answers can be shown side by side
# ---------------------------------------------------------------------------
def build_dual_agents(vector_db) -> tuple[Agent, Agent]:
    kb_agent = Agent(
        role="Knowledge Base Support Agent",
        goal="Answer the customer's question using only the internal knowledge base.",
        backstory=(
            "You answer strictly using the Customer Support Knowledge Base "
            "tool. If the knowledge base does not contain enough information "
            "to answer, say so clearly and suggest contacting support. Never "
            "use outside knowledge and never hallucinate."
        ),
        tools=[make_kb_tool(vector_db)],
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    web_agent = Agent(
        role="Web Search Support Agent",
        goal="Answer the customer's question using only public web search results.",
        backstory=(
            "You answer strictly using the Web Search tool. Summarize what "
            "you find clearly and concisely for a customer support context."
        ),
        tools=[web_search_tool],
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    return kb_agent, web_agent


def answer_dual(query: str, vector_db) -> tuple[str, str]:
    kb_agent, web_agent = build_dual_agents(vector_db)

    kb_task = Task(
        description=f"Customer asked: {query}\n\nAnswer using only the Customer Support Knowledge Base tool.",
        expected_output="A support answer based only on the knowledge base, or a note that it isn't covered there.",
        agent=kb_agent,
    )
    web_task = Task(
        description=f"Customer asked: {query}\n\nAnswer using only the Web Search tool.",
        expected_output="A support answer based on web search results.",
        agent=web_agent,
    )

    crew = Crew(
        agents=[kb_agent, web_agent],
        tasks=[kb_task, web_task],
        process=Process.sequential,
        verbose=True,
    )
    result = crew.kickoff()

    return str(result.tasks_output[0].raw), str(result.tasks_output[1].raw)
