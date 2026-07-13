from rest_framework.pagination import PageNumberPagination


class BoundedPageNumberPagination(PageNumberPagination):
    """
    Same as DRF's default PageNumberPagination (page_size=20 unless the
    client asks for more), except it actually honors a client-supplied
    ?page_size= — capped so a request can't force an unbounded full-table
    fetch. Existing callers that don't pass page_size are unaffected.
    """
    page_size_query_param = "page_size"
    max_page_size = 2000
