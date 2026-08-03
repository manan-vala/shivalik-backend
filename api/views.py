from django.shortcuts import render
from django.http import JsonResponse
# Create your views here.
def health(request):
    return JsonResponse({
        "status": "success",
        "message": "Backend running"
    })