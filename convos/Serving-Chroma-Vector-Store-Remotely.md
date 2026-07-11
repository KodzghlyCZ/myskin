> From: https://gemini.google.com/app/cfe29082b97d643f

# you asked

message time: 2026-05-21 00:15:11

Can you analyze if there's already a way to serve chroma vector store docs through some query request? The thing is that I have an app that uses this but I might want to put the vector store retrieval workload on a different machine

---

# gemini response

Yes, absolutely. Chroma has built-in support for a **Client-Server architecture** specifically designed for this exact use case. You don't need to write a custom API wrapper or change how you query your collections—you just change how you initialize the client in your code. 

Instead of running Chroma as an in-memory or local persistent instance on your main app server, you spin up a standalone Chroma server on your target machine and connect to it over HTTP.

Here is how you can set it up.

---

### Step 1: Spin up the Chroma Server (On the target machine)

You have two main ways to run Chroma as a standalone server on your secondary machine.

**Option A: Using Docker (Recommended)**
The cleanest way is to use the official Docker image. You can spin it up with a single command:

```bash
docker run -d -p 8000:8000 -v ./chroma_data:/chroma/chroma chromadb/chroma:latest
```

**Option B: Using the CLI**
If you have Python and Chroma installed on that machine already, you can launch the server directly from your terminal:

```bash
chroma run --host 0.0.0.0 --port 8000 --path /path/to/your/db_data
```

---

### Step 2: Update your Application Code (On your main machine)

In your main app code, swap out `chromadb.PersistentClient` or `chromadb.Client` for **`chromadb.HttpClient`**. The query syntax (`collection.query(...)`) remains exactly the same.

```python
import chromadb

# Instead of local persistence, point to your external machine's IP/Host
client = chromadb.HttpClient(host="192.168.1.50", port=8000)

# Get your collection exactly like before
collection = client.get_or_create_collection(name="my_documents")

# Query requests work completely out-of-the-box over HTTP
results = collection.query(
    query_texts=["How do I serve chroma docs via network requests?"],
    n_results=3
)

print(results)
```
*(Chroma also provides an `AsyncHttpClient` if your application relies on an async framework like FastAPI or Sanic).*

---

### Critical Considerations for Production

* **Security & Authentication:** Out of the box, Chroma's server doesn't restrict traffic. If you expose port `8000` to the network, anyone can query or wipe your database. You should configure **Static Token Authentication** on the server container using environment variables (`CHROMA_SERVER_AUTHN_PROVIDER=chromadb.auth.token_authn.TokenAuthenticationServerProvider`) and pass a `Bearer` token in your client headers.
* **Embedding Execution Location:** If you rely on Chroma's default embedding function (like `all-MiniLM-L6-v2`), the embedding generation happens **on the machine running the HttpClient** (your app server), and only the resulting vectors are sent over the wire. If your goal is to completely offload the heavy math of embedding generation to the secondary machine, you should explicitly pass pre-calculated vectors using `collection.add(embeddings=[...])` or use an external API service (like OpenAI or Cohere) for generating embeddings.

<FollowUp label="Want to see how to configure token authentication and secure the remote server?" query="How do I configure static token authentication and secure a remote ChromaDB server for production?"/>

---

# you asked

message time: 2026-05-21 00:16:25

Can it serve multiple vector stores at once?

---

# gemini response

Yes, it absolutely can. Chroma handles this flawlessly using two different layers of organization depending on how isolated you want the data to be: **Collections** (standard) and **Multi-Tenancy** (advanced separation).

A single running Chroma server can host thousands of distinct vector spaces simultaneously.

---

### Method 1: Using Collections (Simplest & Most Common)
If you just have different categories of data (e.g., one vector store for "User Manuals", one for "HR Policies", and another for "App Logs"), you manage them as distinct **Collections** within the exact same database. 

On your app server, you simply switch or call whichever collection you need using the same `HttpClient`:

```python
import chromadb

client = chromadb.HttpClient(host="192.168.1.50", port=8000)

# You can toggle back and forth between these dynamically in your code
manuals_vip = client.get_or_create_collection(name="user_manuals")
hr_policies = client.get_or_create_collection(name="hr_policies")

# Query store A
results_a = manuals_vip.query(query_texts=["How to reset router?"], n_results=1)

# Query store B
results_b = hr_policies.query(query_texts=["Maternity leave policy"], n_results=1)
```

---

### Method 2: Multi-Tenancy & Isolated Databases (For SaaS or Hard Isolation)
If you are building an app where **Tenant A must never see Tenant B's data**, or if you want completely distinct databases running on the same server instance, Chroma provides a full Multi-Tenant architecture out of the box (`default_tenant` and `default_database` are used if you don't specify them).

When initializing your client, you can target completely isolated database sandboxes on that same remote machine:

```python
import chromadb

# App connects to the same server, but explicitly requests Tenant X's Company database
client_tenant_a = chromadb.HttpClient(
    host="192.168.1.50", 
    port=8000,
    tenant="tenant_company_a",
    database="finance_db"
)

collection = client_tenant_a.get_collection(name="invoices")
```
> **Note on Setup:** To use multi-tenancy, you'll first use the client's administrative methods (`client.create_tenant(name="...")` and `client.create_database(name="...", tenant="...")`) to provision the spaces on the server before inserting data.

### Summary: Which should you use?
* Use **Collections** if you are managing a single application that just happens to have multiple logical folders or datasets.
* Use **Tenants / Databases** if you are serving different clients, building a multi-user SaaS, or need strict compliance boundaries between the vector datasets on that remote machine.

<FollowUp label="Want to see the code for provisioning tenants and databases dynamically?" query="How do I write the admin code to create and manage multiple tenants and databases in ChromaDB?"/>