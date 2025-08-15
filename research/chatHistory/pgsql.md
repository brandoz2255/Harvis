
langchain_postgres.chat_message_histories.PostgresChatMessageHistory

class langchain_postgres.chat_message_histories.PostgresChatMessageHistory(table_name: str, session_id: str, /, *, sync_connection: Optional[Connection] = None, async_connection: Optional[AsyncConnection] = None)[source]

    Client for persisting chat message history in a Postgres database,

    This client provides support for both sync and async via psycopg >=3.

    The client can create schema in the database and provides methods to add messages, get messages, and clear the chat message history.

    The schema has the following columns:

        id: A serial primary key.

        session_id: The session ID for the chat message history.

        message: The JSONB message content.

        created_at: The timestamp of when the message was created.

    Messages are retrieved for a given session_id and are sorted by the id (which should be increasing monotonically), and correspond to the order in which the messages were added to the history.

    The “created_at” column is not returned by the interface, but has been added for the schema so the information is available in the database.

    A session_id can be used to separate different chat histories in the same table, the session_id should be provided when initializing the client.

    This chat history client takes in a psycopg connection object (either Connection or AsyncConnection) and uses it to interact with the database.

    This design allows to reuse the underlying connection object across multiple instantiations of this class, making instantiation fast.

    This chat history client is designed for prototyping applications that involve chat and are based on Postgres.

    As your application grows, you will likely need to extend the schema to handle more complex queries. For example, a chat application may involve multiple tables like a user table, a table for storing chat sessions / conversations, and this table for storing chat messages for a given session. The application will require access to additional endpoints like deleting messages by user id, listing conversations by user id or ordering them based on last message time, etc.

    Feel free to adapt this implementation to suit your application’s needs.

    Parameters

            session_id (str) – The session ID to use for the chat message history

            table_name (str) – The name of the database table to use

            sync_connection (Optional[psycopg.Connection]) – An existing psycopg connection instance

            async_connection (Optional[psycopg.AsyncConnection]) – An existing psycopg async connection instance

    Usage:

            Use the create_tables or acreate_tables method to set up the table schema in the database.

            Initialize the class with the appropriate session ID, table name, and database connection.

            Add messages to the database using add_messages or aadd_messages.

            Retrieve messages with get_messages or aget_messages.

            Clear the session history with clear or aclear when needed.

    Note

        At least one of sync_connection or async_connection must be provided.

    Examples:

    import uuid

    from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
    from langchain_postgres import PostgresChatMessageHistory
    import psycopg

    # Establish a synchronous connection to the database
    # (or use psycopg.AsyncConnection for async)
    sync_connection = psycopg2.connect(conn_info)

    # Create the table schema (only needs to be done once)
    table_name = "chat_history"
    PostgresChatMessageHistory.create_tables(sync_connection, table_name)

    session_id = str(uuid.uuid4())

    # Initialize the chat history manager
    chat_history = PostgresChatMessageHistory(
        table_name,
        session_id,
        sync_connection=sync_connection
    )

    # Add messages to the chat history
    chat_history.add_messages([
        SystemMessage(content="Meow"),
        AIMessage(content="woof"),
        HumanMessage(content="bark"),
    ])

    print(chat_history.messages)

    Attributes

    messages
    	

    The abstraction required a property.

    Methods

    __init__(table_name, session_id, /, *[, ...])
    	

    Client for persisting chat message history in a Postgres database,

    aadd_messages(messages)
    	

    Add messages to the chat message history.

    aclear()
    	

    Clear the chat message history for the GIVEN session.

    acreate_tables(connection, table_name, /)
    	

    Create the table schema in the database and create relevant indexes.

    add_ai_message(message)
    	

    Convenience method for adding an AI message string to the store.

    add_message(message)
    	

    Add a Message object to the store.

    add_messages(messages)
    	

    Add messages to the chat message history.

    add_user_message(message)
    	

    Convenience method for adding a human message string to the store.

    adrop_table(connection, table_name, /)
    	

    Delete the table schema in the database.

    aget_messages()
    	

    Retrieve messages from the chat message history.

    clear()
    	

    Clear the chat message history for the GIVEN session.

    create_tables(connection, table_name, /)
    	

    Create the table schema in the database and create relevant indexes.

    drop_table(connection, table_name, /)
    	

    Delete the table schema in the database.

    get_messages()
    	

    Retrieve messages from the chat message history.

    __init__(table_name: str, session_id: str, /, *, sync_connection: Optional[Connection] = None, async_connection: Optional[AsyncConnection] = None) → None[source]

        Client for persisting chat message history in a Postgres database,

        This client provides support for both sync and async via psycopg >=3.

        The client can create schema in the database and provides methods to add messages, get messages, and clear the chat message history.

        The schema has the following columns:

            id: A serial primary key.

            session_id: The session ID for the chat message history.

            message: The JSONB message content.

            created_at: The timestamp of when the message was created.

        Messages are retrieved for a given session_id and are sorted by the id (which should be increasing monotonically), and correspond to the order in which the messages were added to the history.

        The “created_at” column is not returned by the interface, but has been added for the schema so the information is available in the database.

        A session_id can be used to separate different chat histories in the same table, the session_id should be provided when initializing the client.

        This chat history client takes in a psycopg connection object (either Connection or AsyncConnection) and uses it to interact with the database.

        This design allows to reuse the underlying connection object across multiple instantiations of this class, making instantiation fast.

        This chat history client is designed for prototyping applications that involve chat and are based on Postgres.

        As your application grows, you will likely need to extend the schema to handle more complex queries. For example, a chat application may involve multiple tables like a user table, a table for storing chat sessions / conversations, and this table for storing chat messages for a given session. The application will require access to additional endpoints like deleting messages by user id, listing conversations by user id or ordering them based on last message time, etc.

        Feel free to adapt this implementation to suit your application’s needs.

        Parameters

                session_id (str) – The session ID to use for the chat message history

                table_name (str) – The name of the database table to use

                sync_connection (Optional[Connection]) – An existing psycopg connection instance

                async_connection (Optional[AsyncConnection]) – An existing psycopg async connection instance

        Return type

            None

        Usage:

                Use the create_tables or acreate_tables method to set up the table schema in the database.

                Initialize the class with the appropriate session ID, table name, and database connection.

                Add messages to the database using add_messages or aadd_messages.

                Retrieve messages with get_messages or aget_messages.

                Clear the session history with clear or aclear when needed.

        Note

            At least one of sync_connection or async_connection must be provided.

        Examples:

        import uuid

        from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
        from langchain_postgres import PostgresChatMessageHistory
        import psycopg

        # Establish a synchronous connection to the database
        # (or use psycopg.AsyncConnection for async)
        sync_connection = psycopg2.connect(conn_info)

        # Create the table schema (only needs to be done once)
        table_name = "chat_history"
        PostgresChatMessageHistory.create_tables(sync_connection, table_name)

        session_id = str(uuid.uuid4())

        # Initialize the chat history manager
        chat_history = PostgresChatMessageHistory(
            table_name,
            session_id,
            sync_connection=sync_connection
        )

        # Add messages to the chat history
        chat_history.add_messages([
            SystemMessage(content="Meow"),
            AIMessage(content="woof"),
            HumanMessage(content="bark"),
        ])

        print(chat_history.messages)

    async aadd_messages(messages: Sequence[BaseMessage]) → None[source]

        Add messages to the chat message history.

        Parameters

            messages (Sequence[BaseMessage]) –
        Return type

            None

    async aclear() → None[source]

        Clear the chat message history for the GIVEN session.

        Return type

            None

    async static acreate_tables(connection: AsyncConnection, table_name: str, /) → None[source]

        Create the table schema in the database and create relevant indexes.

        Parameters

                connection (AsyncConnection) –

                table_name (str) –

        Return type

            None

    add_ai_message(message: Union[AIMessage, str]) → None

        Convenience method for adding an AI message string to the store.

        Please note that this is a convenience method. Code should favor the bulk add_messages interface instead to save on round-trips to the underlying persistence layer.

        This method may be deprecated in a future release.

        Parameters

            message (Union[AIMessage, str]) – The AI message to add.
        Return type

            None

    add_message(message: BaseMessage) → None

        Add a Message object to the store.

        Parameters

            message (BaseMessage) – A BaseMessage object to store.
        Raises

            NotImplementedError – If the sub-class has not implemented an efficient add_messages method.
        Return type

            None

    add_messages(messages: Sequence[BaseMessage]) → None[source]

        Add messages to the chat message history.

        Parameters

            messages (Sequence[BaseMessage]) –
        Return type

            None

    add_user_message(message: Union[HumanMessage, str]) → None

        Convenience method for adding a human message string to the store.

        Please note that this is a convenience method. Code should favor the bulk add_messages interface instead to save on round-trips to the underlying persistence layer.

        This method may be deprecated in a future release.

        Parameters

            message (Union[HumanMessage, str]) – The human message to add to the store.
        Return type

            None

    async static adrop_table(connection: AsyncConnection, table_name: str, /) → None[source]

        Delete the table schema in the database.

        Warning

        This will delete the given table from the database including all the database in the table and the schema of the table.

        Parameters

                connection (AsyncConnection) – Async database connection.

                table_name (str) – The name of the table to create.

        Return type

            None

    async aget_messages() → List[BaseMessage][source]

        Retrieve messages from the chat message history.

        Return type

            List[BaseMessage]

    clear() → None[source]

        Clear the chat message history for the GIVEN session.

        Return type

            None

    static create_tables(connection: Connection, table_name: str, /) → None[source]

        Create the table schema in the database and create relevant indexes.

        Parameters

                connection (Connection) –

                table_name (str) –

        Return type

            None

    static drop_table(connection: Connection, table_name: str, /) → None[source]

        Delete the table schema in the database.

        Warning

        This will delete the given table from the database including all the database in the table and the schema of the table.

        Parameters

                connection (Connection) – The database connection.

                table_name (str) – The name of the table to create.

        Return type

            None

    get_messages() → List[BaseMessage][source]

        Retrieve messages from the chat message history.

        Return type

            List[BaseMessage]

Examples using PostgresChatMessageHistory

    Postgres


