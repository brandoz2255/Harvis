
import os
import requests
from tavily import TavilyClient

# Placeholder for API keys
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

def get_search_results(query: str):
    """
    Uses Tavily to get search results for a given query.
    """
    if not TAVILY_API_KEY:
        return {"error": "Tavily API key not set."}
    
    try:
        client = TavilyClient(api_key=TAVILY_API_KEY)
        response = client.search(query=query, search_depth="advanced")
        return response["results"]
    except Exception as e:
        return {"error": f"An error occurred during search: {str(e)}"}

def research_agent(query: str, model: str = "mistral"):
    """
    A simple research agent that uses a model to generate a search query,
    gets the search results, and then uses the model again to generate a response.
    """
    # For now, we'll just use the user's query directly as the search query.
    # In the future, we could use a model to refine the query.
    search_query = query
    
    search_results = get_search_results(search_query)
    
    if "error" in search_results:
        return search_results["error"]
    
    # For now, we'll just return the search results directly.
    # In the future, we could use a model to process the results and generate a summary.
    return search_results
