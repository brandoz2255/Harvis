https://www.psycopg.org/psycopg3/docs/basic/from_pg2.html



Differences from psycopg2

Psycopg 3 uses the common DBAPI structure of many other database adapters and tries to behave as close as possible to psycopg2. There are however a few differences to be aware of.

Tip

Most of the times, the workarounds suggested here will work with both Psycopg 2 and 3, which could be useful if you are porting a program or writing a program that should work with both Psycopg 2 and 3.
Server-side binding

Psycopg 3 sends the query and the parameters to the server separately, instead of merging them on the client side. Server-side binding works for normal SELECT and data manipulation statements (INSERT, UPDATE, DELETE), but it doesn’t work with many other statements. For instance, it doesn’t work with SET or with NOTIFY:

conn.execute("SET TimeZone TO %s", ["UTC"])
Traceback (most recent call last):
...
psycopg.errors.SyntaxError: syntax error at or near "$1"
LINE 1: SET TimeZone TO $1
                        ^

conn.execute("NOTIFY %s, %s", ["chan", 42])
Traceback (most recent call last):
...
psycopg.errors.SyntaxError: syntax error at or near "$1"
LINE 1: NOTIFY $1, $2
               ^

and with any data definition statement:

conn.execute("CREATE TABLE foo (id int DEFAULT %s)", [42])
Traceback (most recent call last):
...
psycopg.errors.UndefinedParameter: there is no parameter $1
LINE 1: CREATE TABLE foo (id int DEFAULT $1)
                                         ^

Sometimes, PostgreSQL offers an alternative: for instance the set_config() function can be used instead of the SET statement, the pg_notify() function can be used instead of NOTIFY:

conn.execute("SELECT set_config('TimeZone', %s, false)", ["UTC"])

conn.execute("SELECT pg_notify(%s, %s)", ["chan", "42"])

If this is not possible, you must merge the query and the parameter on the client side. You can do so using the psycopg.sql objects:

from psycopg import sql

cur.execute(sql.SQL("CREATE TABLE foo (id int DEFAULT {})").format(42))

or creating a client-side binding cursor such as ClientCursor:

cur = ClientCursor(conn)

cur.execute("CREATE TABLE foo (id int DEFAULT %s)", [42])

If you need ClientCursor often, you can set the Connection.cursor_factory to have them created by default by Connection.cursor(). This way, Psycopg 3 will behave largely the same way of Psycopg 2.

Note that, both server-side and client-side, you can only specify values as parameters (i.e. the strings that go in single quotes). If you need to parametrize different parts of a statement (such as a table name), you must use the psycopg.sql module:

from psycopg import sql

# This will quote the user and the password using the right quotes
# e.g.: ALTER USER "foo" SET PASSWORD 'bar'

conn.execute(

    sql.SQL("ALTER USER {} SET PASSWORD {}")

    .format(sql.Identifier(username), password))

Extended query Protocol

In order to use Server-side binding, psycopg normally uses the extended query protocol to communicate with the backend.

In certain context outside pure PostgreSQL, the extended query protocol is not supported, for instance to query the PgBouncer admin console. In this case you should probably use a ClientCursor. See Simple query protocol for details.
Multiple statements in the same query

As a consequence of using server-side bindings, when parameters are used, it is not possible to execute several statements in the same execute() call, separating them by semicolon:

conn.execute(

    "INSERT INTO foo VALUES (%s); INSERT INTO foo VALUES (%s)",

    (10, 20))
Traceback (most recent call last):
...
psycopg.errors.SyntaxError: cannot insert multiple commands into a prepared statement

One obvious way to work around the problem is to use several execute() calls.

There is no such limitation if no parameters are used. As a consequence, you can compose a multiple query on the client side and run them all in the same execute() call, using the psycopg.sql objects:

from psycopg import sql

conn.execute(

    sql.SQL("INSERT INTO foo VALUES ({}); INSERT INTO foo values ({})"

    .format(10, 20))

or a client-side binding cursor:

cur = psycopg.ClientCursor(conn)

cur.execute(

    "INSERT INTO foo VALUES (%s); INSERT INTO foo VALUES (%s)",

    (10, 20))

Warning

You cannot execute multiple statements in the same query:

    when retrieving a binary result (such as using .execute(..., binary=True);

    when using the pipeline mode.

Warning

If a statement must be executed outside a transaction (such as CREATE DATABASE), it cannot be executed in batch with other statements, even if the connection is in autocommit mode:

conn.autocommit = True

conn.execute("CREATE DATABASE foo; SELECT 1")
Traceback (most recent call last):
...
psycopg.errors.ActiveSqlTransaction: CREATE DATABASE cannot run inside a transaction block

This happens because PostgreSQL itself will wrap multiple statements in a transaction. Note that you will experience a different behaviour in psql (psql will split the queries on semicolons and send them to the server separately).

This is not new in Psycopg 3: the same limitation is present in psycopg2 too.
Multiple results returned from multiple statements

If more than one statement returning results is executed in psycopg2, only the result of the last statement is returned:

cur_pg2.execute("SELECT 1; SELECT 2")

cur_pg2.fetchone()
(2,)

In Psycopg 3 instead, all the results are available. After running the query, the first result will be readily available in the cursor and can be consumed using the usual fetch*() methods. In order to access the following results, you can use the Cursor.results() method (or nextset() before Psycopg 3.3):

cur_pg3.execute("SELECT 1; SELECT 2")

for _ in cur_pg3.results():

   print(cur_pg3.fetchone())
(1,)
(2,)

Remember though that you cannot use server-side bindings to execute more than one statement in the same query, if you are passing parameters to the query.
Different cast rules

In rare cases, especially around variadic functions, PostgreSQL might fail to find a function candidate for the given data types:

conn.execute("SELECT json_build_array(%s, %s)", ["foo", "bar"])
Traceback (most recent call last):
...
psycopg.errors.IndeterminateDatatype: could not determine data type of parameter $1

This can be worked around specifying the argument types explicitly via a cast:

conn.execute("SELECT json_build_array(%s::text, %s::text)", ["foo", "bar"])

You cannot use IN %s with a tuple

IN cannot be used with a tuple as single parameter, as was possible with psycopg2:

conn.execute("SELECT * FROM foo WHERE id IN %s", [(10,20,30)])
Traceback (most recent call last):
...
psycopg.errors.SyntaxError: syntax error at or near "$1"
LINE 1: SELECT * FROM foo WHERE id IN $1
                                      ^

What you can do is to use the = ANY() construct and pass the candidate values as a list instead of a tuple, which will be adapted to a PostgreSQL array:

conn.execute("SELECT * FROM foo WHERE id = ANY(%s)", [[10,20,30]])

Note that ANY() can be used with psycopg2 too, and has the advantage of accepting an empty list of values too as argument, which is not supported by the IN operator instead.
You cannot use IS %s

You cannot use IS %s or IS NOT %s:

conn.execute("SELECT * FROM foo WHERE field IS %s", [None])
Traceback (most recent call last):
...
psycopg.errors.SyntaxError: syntax error at or near "$1"
LINE 1: SELECT * FROM foo WHERE field IS $1
                                     ^

This is probably caused by the fact that IS is not a binary predicate in PostgreSQL; rather, IS NULL and IS NOT NULL are unary predicates and you cannot use IS with anything else on the right hand side. Testing in psql:

=# SELECT 10 IS 10;
ERROR:  syntax error at or near "10"
LINE 1: SELECT 10 IS 10;
                     ^

What you can do is to use IS [NOT] DISTINCT FROM predicate instead: IS NOT DISTINCT FROM %s can be used in place of IS %s (please pay attention to the awkwardly reversed NOT):

conn.execute("SELECT * FROM foo WHERE field IS NOT DISTINCT FROM %s", [None])

Analogously you can use IS DISTINCT FROM %s as a parametric version of IS NOT %s.
Cursors subclasses

In psycopg2, a few cursor subclasses allowed to return data in different form than tuples. In Psycopg 3 the same can be achieved by setting a row factory:

    instead of RealDictCursor you can use dict_row;

    instead of NamedTupleCursor you can use namedtuple_row.

Other row factories are available in the psycopg.rows module. There isn’t an object behaving like DictCursor (whose results are indexable both by column position and by column name).

from psycopg.rows import dict_row, namedtuple_row

# By default, every cursor will return dicts.
conn = psycopg.connect(DSN, row_factory=dict_row)

# You can set a row factory on a single cursor too.
cur = conn.cursor(row_factory=namedtuple_row)

Different adaptation system

The adaptation system has been completely rewritten, in order to address server-side parameters adaptation, but also to consider performance, flexibility, ease of customization.

The default behaviour with builtin data should be what you would expect. If you have customised the way to adapt data, or if you are managing your own extension types, you should look at the new adaptation system.

See also

    Adapting basic Python types for the basic behaviour.

    Data adaptation configuration for more advanced use.

Copy is no longer file-based

psycopg2 exposes a few copy methods to interact with PostgreSQL COPY. Their file-based interface doesn’t make it easy to load dynamically-generated data into a database.

There is now a single copy() method, which is similar to psycopg2 copy_expert() in accepting a free-form COPY command and returns an object to read/write data, block-wise or record-wise. The different usage pattern also enables COPY to be used in async interactions.

See also

See Using COPY TO and COPY FROM for the details.
with connection

In psycopg2, using the syntax with connection, only the transaction is closed, not the connection. This behaviour is surprising for people used to several other Python classes wrapping resources, such as files.

In Psycopg 3, using with connection will close the connection at the end of the with block, making handling the connection resources more familiar.

In order to manage transactions as blocks you can use the Connection.transaction() method, which allows for finer control, for instance to use nested transactions.

See also

See Transaction contexts for details.
callproc() is gone

cursor.callproc() is not implemented. The method has a simplistic semantic which doesn’t account for PostgreSQL positional parameters, procedures, set-returning functions… Use a normal execute() with SELECT function_name(...) or CALL procedure_name(...) instead.
client_encoding is gone

Psycopg automatically uses the database client encoding to decode data to Unicode strings. Use ConnectionInfo.encoding if you need to read the encoding. You can select an encoding at connection time using the client_encoding connection parameter and you can change the encoding of a connection by running a SET client_encoding statement… But why would you?
Transaction characteristics attributes don’t affect autocommit sessions

Transactions characteristics attributes such as read_only don’t affect automatically autocommit sessions: they only affect the implicit transactions started by non-autocommit sessions and the transactions created by the transaction() block (for both autocommit and non-autocommit connections).

If you want to put an autocommit transaction in read-only mode, please use the default_transaction_read_only GUC, for instance executing the statement SET default_transaction_read_only TO true.
No default infinity dates handling

PostgreSQL can represent a much wider range of dates and timestamps than Python. While Python dates are limited to the years between 1 and 9999 (represented by constants such as datetime.date.min and max), PostgreSQL dates extend to BC dates and past the year 10K. Furthermore PostgreSQL can also represent symbolic dates “infinity”, in both directions.

In psycopg2, by default, infinity dates and timestamps map to ‘date.max’ and similar constants. This has the problem of creating a non-bijective mapping (two Postgres dates, infinity and 9999-12-31, both map to the same Python date). There is also the perversity that valid Postgres dates, greater than Python date.max but arguably lesser than infinity, will still overflow.

In Psycopg 3, every date greater than year 9999 will overflow, including infinity. If you would like to customize this mapping (for instance flattening every date past Y10K on date.max) you can subclass and adapt the appropriate loaders: take a look at this example to see how.
What’s new in Psycopg 3

    Asynchronous support

    Server-side parameters binding

    Prepared statements

    Binary communication

    Python-based COPY support

    Support for static typing

    A redesigned connection pool

    Direct access to the libpq functionalities

