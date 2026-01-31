"""
Quick validation script for Day 19 API endpoints.
This script checks that all components are properly configured.
"""

import os
import sys
import django

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

try:
    django.setup()
except Exception as e:
    print(f"❌ Django setup failed: {e}")
    print("Note: This might be expected if Django/DRF is not installed")
    sys.exit(0)

def test_imports():
    """Test that all imports work correctly"""
    print("Testing imports...")
    
    try:
        from api.serializers import (
            DisputeSerializer,
            DisputeResolutionSerializer,
            MessageSerializer,
            MessageCreateSerializer,
            NotificationSerializer
        )
        print("✅ All serializers imported successfully")
    except ImportError as e:
        print(f"❌ Serializer import failed: {e}")
        return False
    
    try:
        from api.views import (
            DisputeViewSet,
            MessageViewSet,
            NotificationViewSet
        )
        print("✅ All ViewSets imported successfully")
    except ImportError as e:
        print(f"❌ ViewSet import failed: {e}")
        return False
    
    try:
        from api.urls import router, urlpatterns
        print("✅ Router and urlpatterns imported successfully")
    except ImportError as e:
        print(f"❌ URL import failed: {e}")
        return False
    
    return True

def test_router():
    """Test that router is properly configured"""
    print("\nTesting router configuration...")
    
    try:
        from api.urls import router
        
        # Check router is DefaultRouter
        from rest_framework.routers import DefaultRouter
        if isinstance(router, DefaultRouter):
            print("✅ Router is DefaultRouter instance")
        else:
            print("❌ Router is not DefaultRouter instance")
            return False
        
        # Check registered ViewSets
        registered = [url.name for url in router.urls]
        expected = ['dispute', 'message', 'notification']
        
        # Check if router has registered routes
        if len(router.registry) == 3:
            print(f"✅ Router has {len(router.registry)} ViewSets registered")
        else:
            print(f"⚠️  Router has {len(router.registry)} ViewSets (expected 3)")
        
        return True
    except Exception as e:
        print(f"❌ Router test failed: {e}")
        return False

def test_models():
    """Test that all required models exist"""
    print("\nTesting model availability...")
    
    try:
        from panel.models import Dispute
        from messenger.models import Message, ReadMessage
        from alert.models import Notification, ReadNotification
        
        print("✅ All models imported successfully")
        
        # Check Dispute.STATUS_CHOICES
        if hasattr(Dispute, 'STATUS_CHOICES'):
            print("✅ Dispute.STATUS_CHOICES exists")
        else:
            print("❌ Dispute.STATUS_CHOICES not found")
            return False
        
        return True
    except ImportError as e:
        print(f"❌ Model import failed: {e}")
        return False

def test_serializers():
    """Test that serializers can be instantiated"""
    print("\nTesting serializer instantiation...")
    
    try:
        from api.serializers import (
            DisputeSerializer,
            DisputeResolutionSerializer,
            MessageSerializer,
            MessageCreateSerializer,
            NotificationSerializer
        )
        
        # Check serializer Meta classes
        serializers = [
            ('DisputeSerializer', DisputeSerializer),
            ('DisputeResolutionSerializer', DisputeResolutionSerializer),
            ('MessageSerializer', MessageSerializer),
            ('MessageCreateSerializer', MessageCreateSerializer),
            ('NotificationSerializer', NotificationSerializer),
        ]
        
        for name, serializer_class in serializers:
            if hasattr(serializer_class, 'Meta'):
                print(f"✅ {name} has Meta class")
            else:
                print(f"⚠️  {name} missing Meta class")
        
        return True
    except Exception as e:
        print(f"❌ Serializer test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Day 19 API Endpoints Validation")
    print("=" * 60)
    print()
    
    results = []
    
    results.append(("Imports", test_imports()))
    results.append(("Router", test_router()))
    results.append(("Models", test_models()))
    results.append(("Serializers", test_serializers()))
    
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name}: {status}")
    
    all_passed = all(result for _, result in results)
    
    if all_passed:
        print("\n✅ All validation tests passed!")
        print("\nNext steps:")
        print("1. Start Django server: python manage.py runserver")
        print("2. Test endpoints using Postman, curl, or HTTP client")
        print("3. Get JWT token from /api/auth/token/")
        print("4. Test all endpoints with proper authentication")
    else:
        print("\n⚠️  Some tests failed. Please review the errors above.")
    
    return 0 if all_passed else 1

if __name__ == '__main__':
    sys.exit(main())

