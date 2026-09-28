import streamlit as st

from support_core import DATA_DIR, answer_dual, build_vector_db

st.set_page_config(page_title="Multi-Agent Customer Support", page_icon="🤖")

st.title("🤖 Multi-Agent Customer Support")
st.caption(
    "Ask a customer-support question and get answers from both the "
    "internal knowledge base and the web."
)

with st.sidebar:
    st.header("Knowledge Base")
    uploaded_file = st.file_uploader("Upload a .txt file of customer support content", type=["txt"])


@st.cache_resource(show_spinner="Indexing knowledge base...")
def get_vector_db(file_bytes: bytes, filename: str):
    saved_path = DATA_DIR / filename
    saved_path.write_bytes(file_bytes)
    return build_vector_db(saved_path)


if uploaded_file is not None:
    vector_db = get_vector_db(uploaded_file.getvalue(), uploaded_file.name)
    st.sidebar.success(f"Using uploaded file: {uploaded_file.name}")
else:
    default_path = DATA_DIR / "amazon_customer_support.txt"
    vector_db = get_vector_db(default_path.read_bytes(), default_path.name)
    st.sidebar.info("Using default Amazon customer support sample data.")

with st.form("query_form"):
    query = st.text_input(
        "Customer Query",
        placeholder="e.g. Can I change my shipping address after ordering?",
    )
    submitted = st.form_submit_button("Submit Query", type="primary")

if submitted and query.strip():
    with st.spinner("Agents are researching your question..."):
        kb_answer, web_answer = answer_dual(query, vector_db)

    st.subheader("🤖 Assistant Answer")
    st.write(kb_answer)

    st.subheader("🌐 Web Search Answer")
    st.write(web_answer)
