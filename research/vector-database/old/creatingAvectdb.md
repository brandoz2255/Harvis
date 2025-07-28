What is PGVector?

PGVector is a Postgres vector store integration that allows you to store and query vector embeddings within a PostgreSQL database.  This is particularly useful for applications involving similarity searches, such as in retrieval-augmented generation (RAG) systems.

Setup and Installation

Getting started with PGVector and LangChain is a straightforward process. You'll need to install the necessary Python package and get a PostgreSQL instance with the pgvector extension running.

    Install the LangChain Postgres package:
    Bash

pip install -qU langchain-postgres

Run a Docker container: The easiest way to get a compatible PostgreSQL instance up and running is by using Docker. The following command will start a container with the necessary configurations:
Bash

docker run --name pgvector-container -e POSTGRES_USER=langchain -e POSTGRES_PASSWORD=langchain -e POSTGRES_DB=langchain -p 6024:5432 -d pgvector/pgvector:pg16

Initializing the Vector Store

Once you have your database running, you can initialize the PGVector store in your Python application. This step connects to your database and prepares it for storing vector embeddings.

Here's how to initialize the PGVector store:
Python

from langchain_postgres import PGVector
from your_embedding_library import YourEmbeddings # Replace with your actual embedding function

# Connection string for your PostgreSQL database
connection_string = "postgresql+psycopg2://langchain:langchain@localhost:6024/langchain"

# An embedding function
embeddings = YourEmbeddings()

# The name for your collection of vectors
collection_name = "my_vector_collection"

# Initialize the vector store
vectorstore = PGVector(
    connection=connection_string,
    embeddings=embeddings,
    collection_name=collection_name,
)

Key Parameters for Initialization: 

    connection: Your PostgreSQL connection string.

embeddings: The embedding function you'll be using.

collection_name : The name of the collection for your vectors. Note that this is not a table name. 

distance_strategy: The method for calculating the distance between vectors. The default is Cosine similarity. 

pre_delete_collection: If set to 

True, it will delete any existing collection with the same name. This is useful for testing. 

use_jsonb : It is highly recommended to use JSONB for metadata as it is more efficient for querying. 

Adding Data to the Vector Store

You can add your documents and their corresponding vector embeddings to the store in several ways.

Adding Documents

The most common method is to add documents directly. LangChain will handle the process of creating embeddings and storing them.

    add_documents(documents): This method takes a list of Document objects and adds them to the vector store. 

Python

    from langchain_core.documents import Document

    docs = [
        Document(page_content="the cat sat on the mat"),
        Document(page_content="the dog chased the ball"),
    ]

    vectorstore.add_documents(docs)

Adding Texts

If you have a list of texts, you can add them directly.

    add_texts(texts, metadatas=None, ids=None): This method runs your texts through the embedding function and adds them to the vector store. You can also provide optional metadata and IDs. 

Python

    texts = ["hello world", "hello galaxy"]
    metadatas = [{"source": "A"}, {"source": "B"}]

    vectorstore.add_texts(texts, metadatas=metadatas)

Adding Embeddings Directly

If you have pre-computed embeddings, you can add them along with the corresponding texts.

    add_embeddings(texts, embeddings, metadatas=None, ids=None): This method allows you to add texts and their embeddings directly to the store. 

Searching for Similar Documents

Once your data is stored, you can perform similarity searches to find relevant documents.

    similarity_search(query, k=4, filter=None): This is the most common search method. It returns the 

    k most similar documents to a given query. 

Python

query = "a furry animal"
similar_docs = vectorstore.similarity_search(query)
print(similar_docs)

similarity_search_with_score(query, k=4, filter=None): This method is similar to the above but also returns the relevance scores of the documents. 

max_marginal_relevance_search(query, k=4, fetch_k=20): This method aims to find a set of documents that are not only similar to the query but also diverse among themselves, which helps in avoiding redundant results. 

Deleting Data

You can manage your vector store by deleting specific vectors or entire collections.

    delete(ids): Deletes vectors based on their IDs. 

delete_collection(): Deletes the entire collection. 
