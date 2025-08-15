Persistent AI Chatbot with Google Generative AI, LangChain, and PostgreSQL

This repository provides a memory-powered conversational AI chatbot built with LangChain, Google Generative AI, and Gradio, integrated with PostgreSQL for persistent storage of conversation history. This project demonstrates how to create a chatbot that remembers user interactions, enhancing user experience by maintaining context across multiple conversations.
Features

    Memory-Powered Conversations: The chatbot recalls past user interactions, enabling more context-aware responses.
    Persistent Storage: Uses PostgreSQL to store and retrieve conversation history, making the chatbot robust and scalable.
    Interactive Gradio Interface: A user-friendly interface for seamless interaction with the chatbot.
    Google Generative AI Integration: Leverages Google’s state-of-the-art Generative AI for high-quality responses.

Prerequisites

    Python 3.10+
    PostgreSQL installed and configured
    Google Generative AI API Key

Installation

Clone the repository:

git clone https://github.com/vinodvpillai/persistent-ai-chatbot-with-postgresql.git
cd persistent-ai-chatbot-with-postgresql

Install the required Python packages:

pip install langchain langchain-google-genai gradio pydantic python-dotenv psycopg2-binary

Set up the PostgreSQL database:

    Create a database named chatdb.
    Run the following SQL commands to create the chat_history table:

    CREATE DATABASE chatdb;

    \c chatdb  -- Connect to the chatdb database

    CREATE TABLE chat_history (
        id serial4 NOT NULL, 
        user_id VARCHAR(255),
        conversation_id VARCHAR(255),
        message_type VARCHAR(50),
        content TEXT,
        CONSTRAINT ai_chat_history_pkey PRIMARY KEY (id)
    );
    CREATE INDEX chat_history_user_id ON public.chat_history USING btree (user_id, conversation_id);

Set up your environment variables:

    Create a .env file in the root directory and add:

    GOOGLE_API_KEY=<your_google_api_key>
    GOOGLE_MODEL=<your_google_model>

    POSTGRES_HOST=<your_database_host>
    POSTGRES_PORT=<your_database_port>
    POSTGRES_DB=<your_database_name>
    POSTGRES_USER=<your_database_username>
    POSTGRES_PASSWORD=<your_database_password>

Usage
Running the Chatbot

Run the script:

python main.py

    Access the Gradio interface:
        The terminal will provide a local URL. Open this link in your browser to start interacting with the chatbot.

Example Conversation

    User: "Hi, I would like to know about AI."
    AI: "Artificial Intelligence (AI) refers to the simulation of human intelligence in machines..."
    User: "Can you remember my name?"
    AI: "Yes, your name is Vinod."

Code Overview
Main Components

    Environment Setup:
        Loads API keys and model configuration from .env for secure handling.

    Database Integration:
        Uses psycopg2 to connect to PostgreSQL and manage persistent chat history.

    Memory Management:
        A custom PostgresChatHistory class loads, adds, and clears messages from the database.

    Gradio Interface:
        Provides an intuitive web interface for user interaction, displaying chat history as a conversation with labels [username] and [AI].

Functionality Breakdown

    PostgresChatHistory Class:
        Overrides the default in-memory storage with database-backed methods to add, fetch, and clear messages.
    get_session_history Function:
        Retrieves or initializes chat history based on user and conversation IDs.
    Gradio UI:
        Users input their username and query, and the chatbot responds with memory-driven replies.

Configuration

Ensure that your PostgreSQL credentials (user, password, host, port) are securely set in your script or environment.
Dependencies

    LangChain: Framework for integrating language models.
    Gradio: Web-based UI for machine learning models.
    psycopg2-binary: PostgreSQL database adapter for Python.
    Pydantic: Data validation and settings management.
    python-dotenv: Load environment variables from a .env file.

Troubleshooting

    Database Connection Errors: Ensure PostgreSQL is running and credentials are correct.
    API Key Issues: Verify your Google Generative AI API key and permissions.

Future Enhancements

    Add multi-session management with unique conversation IDs.
    Implement user authentication for better security.
    Deploy the chatbot on cloud platforms for broader access.

License

This project is licensed under the MIT License. See LICENSE for details.
Acknowledgments

    LangChain for memory and model management.
    Gradio for the interactive user interface.
    Google Generative AI for powering intelligent responses.

