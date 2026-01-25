"""
Unit tests for Flutterwave withdrawal/transfer API integration

Tests verify that transfer beneficiary creation, transfer initiation, and transfer verification work correctly.
"""

from django.test import TestCase
from unittest.mock import patch, Mock
from decimal import Decimal

from wallet.flutterwave_service import FlutterwaveService


class FlutterwaveWithdrawalTests(TestCase):
    """Test Flutterwave withdrawal/transfer API methods"""
    
    def setUp(self):
        """Set up test data"""
        self.service = FlutterwaveService()
    
    @patch('wallet.flutterwave_service.requests.post')
    def test_create_transfer_beneficiary_success(self, mock_post):
        """Test successful transfer beneficiary creation"""
        # Mock successful response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'data': {
                'id': 12345,
                'account_number': '0123456789',
                'account_name': 'John Doe',
                'bank_code': '058',
                'bank_name': 'Guaranty Trust Bank'
            },
            'message': 'Beneficiary created'
        }
        mock_post.return_value = mock_response
        
        result = self.service.create_transfer_beneficiary(
            account_number='0123456789',
            bank_code='058',
            account_name='John Doe',
            email='john@example.com'
        )
        
        self.assertTrue(result['success'])
        self.assertEqual(result['beneficiary_id'], 12345)
        self.assertEqual(result['account_number'], '0123456789')
        self.assertEqual(result['account_name'], 'John Doe')
        self.assertEqual(result['bank_code'], '058')
        self.assertEqual(result['bank_name'], 'Guaranty Trust Bank')
        
        # Verify API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn('/beneficiaries', call_args[0][0])
        self.assertEqual(call_args[1]['json']['account_number'], '0123456789')
        self.assertEqual(call_args[1]['json']['bank_code'], '058')
    
    @patch('wallet.flutterwave_service.requests.post')
    def test_create_transfer_beneficiary_failure(self, mock_post):
        """Test transfer beneficiary creation failure"""
        # Mock failed response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'error',
            'message': 'Invalid bank code'
        }
        mock_post.return_value = mock_response
        
        result = self.service.create_transfer_beneficiary(
            account_number='0123456789',
            bank_code='999',  # Invalid bank code
            account_name='John Doe'
        )
        
        self.assertFalse(result['success'])
        self.assertIsNone(result['beneficiary_id'])
        self.assertIn('Invalid bank code', result['message'])
    
    @patch('wallet.flutterwave_service.requests.post')
    def test_create_transfer_beneficiary_not_configured(self, mock_post):
        """Test transfer beneficiary creation when Flutterwave is not configured"""
        # Mock no secret key
        original_secret = self.service.secret_key
        self.service.secret_key = None
        
        result = self.service.create_transfer_beneficiary(
            account_number='0123456789',
            bank_code='058',
            account_name='John Doe'
        )
        
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], 'Flutterwave not configured')
        
        # Restore secret key
        self.service.secret_key = original_secret
        mock_post.assert_not_called()
    
    @patch('wallet.flutterwave_service.requests.post')
    def test_initiate_transfer_success(self, mock_post):
        """Test successful transfer initiation"""
        # Mock successful response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'data': {
                'id': 67890,
                'reference': 'ref_test789',
                'amount': '5000.00',
                'status': 'NEW'
            },
            'message': 'Transfer queued'
        }
        mock_post.return_value = mock_response
        
        result = self.service.initiate_transfer(
            amount=Decimal('5000.00'),
            beneficiary_id=12345,
            narration='Withdrawal request',
            reference='withdrawal_ref_001'
        )
        
        self.assertTrue(result['success'])
        self.assertEqual(result['transfer_id'], 67890)
        self.assertEqual(result['reference'], 'ref_test789')
        self.assertEqual(result['amount'], Decimal('5000.00'))
        self.assertEqual(result['status'], 'NEW')
        
        # Verify API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn('/transfers', call_args[0][0])
        self.assertEqual(call_args[1]['json']['beneficiary_id'], 12345)
        self.assertEqual(call_args[1]['json']['amount'], '5000.0')
    
    @patch('wallet.flutterwave_service.requests.post')
    def test_initiate_transfer_failure(self, mock_post):
        """Test transfer initiation failure"""
        # Mock failed response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'error',
            'message': 'Insufficient balance'
        }
        mock_post.return_value = mock_response
        
        result = self.service.initiate_transfer(
            amount=Decimal('10000.00'),
            beneficiary_id=12345
        )
        
        self.assertFalse(result['success'])
        self.assertIsNone(result['transfer_id'])
        self.assertIn('Insufficient balance', result['message'])
    
    @patch('wallet.flutterwave_service.requests.post')
    def test_initiate_transfer_not_configured(self, mock_post):
        """Test transfer initiation when Flutterwave is not configured"""
        # Mock no secret key
        original_secret = self.service.secret_key
        self.service.secret_key = None
        
        result = self.service.initiate_transfer(
            amount=Decimal('100.00'),
            beneficiary_id=12345
        )
        
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], 'Flutterwave not configured')
        
        # Restore secret key
        self.service.secret_key = original_secret
        mock_post.assert_not_called()
    
    @patch('wallet.flutterwave_service.requests.get')
    def test_verify_transfer_success_by_id(self, mock_get):
        """Test successful transfer verification using transfer_id"""
        # Mock successful response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'data': {
                'id': 67890,
                'reference': 'ref_test789',
                'amount': '5000.00',
                'status': 'SUCCESSFUL',
                'beneficiary_id': 12345
            },
            'message': 'Transfer retrieved'
        }
        mock_get.return_value = mock_response
        
        result = self.service.verify_transfer(transfer_id=67890)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['amount'], Decimal('5000.00'))
        self.assertEqual(result['transfer_id'], 67890)
        self.assertEqual(result['reference'], 'ref_test789')
        self.assertEqual(result['beneficiary_id'], 12345)
        
        # Verify API call
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertIn('/transfers/67890', call_args[0][0])
    
    @patch('wallet.flutterwave_service.requests.get')
    def test_verify_transfer_success_by_reference(self, mock_get):
        """Test successful transfer verification using reference"""
        # Mock successful response (list format for reference query)
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'data': [{
                'id': 67890,
                'reference': 'ref_test789',
                'amount': '5000.00',
                'status': 'SUCCESSFUL',
                'beneficiary_id': 12345
            }]
        }
        mock_get.return_value = mock_response
        
        result = self.service.verify_transfer(reference='ref_test789')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'success')
        
        # Verify API call used reference
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertIn('reference=ref_test789', call_args[0][0])
    
    @patch('wallet.flutterwave_service.requests.get')
    def test_verify_transfer_pending_status(self, mock_get):
        """Test transfer verification with pending status"""
        # Mock pending response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'data': {
                'id': 67890,
                'reference': 'ref_test789',
                'amount': '5000.00',
                'status': 'PENDING',
                'beneficiary_id': 12345
            }
        }
        mock_get.return_value = mock_response
        
        result = self.service.verify_transfer(transfer_id=67890)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'pending')
    
    @patch('wallet.flutterwave_service.requests.get')
    def test_verify_transfer_new_status(self, mock_get):
        """Test transfer verification with NEW status (normalized to pending)"""
        # Mock NEW status response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'data': {
                'id': 67890,
                'reference': 'ref_test789',
                'amount': '5000.00',
                'status': 'NEW',
                'beneficiary_id': 12345
            }
        }
        mock_get.return_value = mock_response
        
        result = self.service.verify_transfer(transfer_id=67890)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'pending')  # NEW normalized to pending
    
    @patch('wallet.flutterwave_service.requests.get')
    def test_verify_transfer_failed_status(self, mock_get):
        """Test transfer verification with failed status"""
        # Mock failed response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'data': {
                'id': 67890,
                'reference': 'ref_test789',
                'amount': '5000.00',
                'status': 'FAILED',
                'beneficiary_id': 12345
            }
        }
        mock_get.return_value = mock_response
        
        result = self.service.verify_transfer(transfer_id=67890)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'failed')
    
    @patch('wallet.flutterwave_service.requests.get')
    def test_verify_transfer_not_found(self, mock_get):
        """Test transfer verification when transfer is not found"""
        # Mock not found response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'error',
            'message': 'Transfer not found'
        }
        mock_get.return_value = mock_response
        
        result = self.service.verify_transfer(transfer_id=99999)
        
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'pending')
        self.assertIn('Transfer not found', result['message'])
    
    def test_verify_transfer_no_identifier(self):
        """Test transfer verification without transfer_id or reference"""
        result = self.service.verify_transfer()
        
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'pending')
        self.assertIn('Either transfer_id or reference is required', result['message'])
    
    @patch('wallet.flutterwave_service.requests.get')
    def test_verify_transfer_not_configured(self, mock_get):
        """Test transfer verification when Flutterwave is not configured"""
        # Mock no secret key
        original_secret = self.service.secret_key
        self.service.secret_key = None
        
        result = self.service.verify_transfer(transfer_id=67890)
        
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(result['message'], 'Flutterwave not configured')
        
        # Restore secret key
        self.service.secret_key = original_secret
        mock_get.assert_not_called()
    
    @patch('wallet.flutterwave_service.requests.post')
    def test_create_transfer_beneficiary_exception_handling(self, mock_post):
        """Test exception handling in create_transfer_beneficiary"""
        # Mock exception
        mock_post.side_effect = Exception('Network error')
        
        result = self.service.create_transfer_beneficiary(
            account_number='0123456789',
            bank_code='058',
            account_name='John Doe'
        )
        
        self.assertFalse(result['success'])
        self.assertIn('Error:', result['message'])
    
    @patch('wallet.flutterwave_service.requests.post')
    def test_initiate_transfer_exception_handling(self, mock_post):
        """Test exception handling in initiate_transfer"""
        # Mock exception
        mock_post.side_effect = Exception('Network error')
        
        result = self.service.initiate_transfer(
            amount=Decimal('100.00'),
            beneficiary_id=12345
        )
        
        self.assertFalse(result['success'])
        self.assertIn('Error:', result['message'])
    
    @patch('wallet.flutterwave_service.requests.get')
    def test_verify_transfer_exception_handling(self, mock_get):
        """Test exception handling in verify_transfer"""
        # Mock exception
        mock_get.side_effect = Exception('Network error')
        
        result = self.service.verify_transfer(transfer_id=67890)
        
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'pending')
        self.assertIn('Verification error:', result['message'])
