"""
HTTP API client with retry logic and rate limiting for Coralogix API.
"""

import time
from typing import Dict, Any, Optional, List
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog

from .config import Config


class CoralogixAPIError(Exception):
    """Custom exception for Coralogix API errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, response_data: Optional[Dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class APIClient:
    """HTTP client for Coralogix API with retry logic and rate limiting."""
    
    def __init__(self, config: Config, team: str = 'teama'):
        """
        Initialize API client.
        
        Args:
            config: Configuration object
            team: Which team to connect to ('teama' or 'teamb')
        """
        self.config = config
        self.team = team
        self.logger = structlog.get_logger(f"api_client_{team}")
        
        # Set base URL and headers based on team
        if team == 'teama':
            self.base_url = config.cx_api_url_teama
            self.headers = config.teama_headers
        elif team == 'teamb':
            self.base_url = config.cx_api_url_teamb
            self.headers = config.teamb_headers
        else:
            raise ValueError(f"Invalid team: {team}. Must be 'teama' or 'teamb'")
        
        # Initialize HTTP client
        self.client = httpx.Client(
            base_url=self.base_url,
            headers=self.headers,
            timeout=30.0
        )
        
        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 1.0 / config.api_rate_limit_per_second
    
    def _rate_limit(self):
        """Implement rate limiting."""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        
        if time_since_last_request < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last_request
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError))
    )
    def _make_request(self, method: str, endpoint: str, **kwargs) -> httpx.Response:
        """
        Make HTTP request with retry logic.
        
        Args:
            method: HTTP method
            endpoint: API endpoint
            **kwargs: Additional arguments for httpx request
        
        Returns:
            HTTP response
        
        Raises:
            CoralogixAPIError: On API errors
        """
        self._rate_limit()
        
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        start_time = time.time()
        
        try:
            response = self.client.request(method, endpoint, **kwargs)
            response_time = time.time() - start_time
            
            self.logger.info(
                "API request completed",
                method=method,
                url=url,
                status_code=response.status_code,
                response_time_ms=round(response_time * 1000, 2)
            )
            
            # Raise for HTTP errors
            response.raise_for_status()
            
            return response
            
        except httpx.HTTPStatusError as e:
            response_time = time.time() - start_time
            
            self.logger.error(
                "API request failed",
                method=method,
                url=url,
                status_code=e.response.status_code,
                response_time_ms=round(response_time * 1000, 2),
                error=str(e)
            )
            
            # Try to get error details from response
            try:
                error_data = e.response.json()
                error_message = f"API request failed: {e}"
                if error_data:
                    # Add detailed error information
                    if 'message' in error_data:
                        error_message += f" - {error_data['message']}"
                    if 'details' in error_data:
                        error_message += f" - Details: {error_data['details']}"
                    if 'errors' in error_data:
                        error_message += f" - Errors: {error_data['errors']}"
            except:
                error_data = {"message": e.response.text}
                error_message = f"API request failed: {e} - Response: {e.response.text}"

            # Log detailed error for debugging
            self.logger.error(
                "Detailed API error",
                status_code=e.response.status_code,
                error_data=error_data,
                response_text=e.response.text[:500]  # First 500 chars
            )

            raise CoralogixAPIError(
                error_message,
                status_code=e.response.status_code,
                response_data=error_data
            )
        
        except httpx.RequestError as e:
            response_time = time.time() - start_time
            
            self.logger.error(
                "API request error",
                method=method,
                url=url,
                response_time_ms=round(response_time * 1000, 2),
                error=str(e)
            )
            
            raise CoralogixAPIError(f"Request error: {e}")
    
    def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make GET request."""
        response = self._make_request("GET", endpoint, params=params)
        return response.json()
    
    def post(self, endpoint: str, json_data: Optional[Dict] = None,
             data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make POST request."""
        response = self._make_request("POST", endpoint, json=json_data, data=data, params=params)
        return response.json()
    
    def put(self, endpoint: str, json_data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make PUT request."""
        response = self._make_request("PUT", endpoint, json=json_data)
        return response.json()
    
    def delete(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Make DELETE request."""
        response = self._make_request("DELETE", endpoint)
        
        # DELETE requests might not return JSON
        if response.content:
            try:
                return response.json()
            except:
                return {"message": "Deleted successfully"}
        return None
    
    def get_paginated(self, endpoint: str, params: Optional[Dict] = None, 
                     page_size: int = 100) -> List[Dict[str, Any]]:
        """
        Get all results from a paginated endpoint.
        
        Args:
            endpoint: API endpoint
            params: Query parameters
            page_size: Number of items per page
        
        Returns:
            List of all items
        """
        all_items = []
        page = 1
        params = params or {}
        
        while True:
            page_params = {
                **params,
                'page': page,
                'limit': page_size
            }
            
            response = self.get(endpoint, params=page_params)
            
            # Handle different pagination response formats
            if 'items' in response:
                items = response['items']
                total_pages = response.get('total_pages', 1)
            elif 'data' in response:
                items = response['data']
                total_pages = response.get('pagination', {}).get('total_pages', 1)
            elif 'actions' in response:
                # Handle actions API response format
                items = response['actions']
                total_pages = 1  # Actions API doesn't seem to use pagination
            elif 'alertDefs' in response:
                # Handle alerts API response format
                items = response['alertDefs']
                # Handle pagination for alerts API
                pagination = response.get('pagination', {})
                if pagination.get('nextPageToken'):
                    total_pages = page + 1  # Continue to next page
                else:
                    total_pages = page  # Last page
            else:
                # Assume response is a list
                items = response if isinstance(response, list) else []
                total_pages = 1
            
            all_items.extend(items)
            
            if page >= total_pages or not items:
                break
            
            page += 1
        
        self.logger.info(
            "Paginated request completed",
            endpoint=endpoint,
            total_items=len(all_items),
            pages_fetched=page
        )
        
        return all_items
    
    def close(self):
        """Close the HTTP client."""
        self.client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
