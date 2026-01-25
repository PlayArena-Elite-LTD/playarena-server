"""
Unit tests for Paystack withdrawal/transfer API integration

Tests verify that transfer recipient creation, transfer initiation, and transfer verification work correctly.
"""

from django.test import TestCase
from unittest.mock import patch, Mock
from decimal import Decimal
import json

from wallet.paystack_service import PaystackService


class PaystackWithdrawalTests(TestCase):
    """Test Paystack withdrawal/transfer API methods"""
    
    def setUp(self):
        """Set up test data"""
        self.service = PaystackService()
    
    @patch('wallet.paystack_service.requests.post')
    def test_create_transfer_recipient_success(self, mock_post):
        """Test successful transfer recipient creation"""
        # Mock successful response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': True,
            'data': {
                'recipient_code': 'RCP_test123',
                'details': {
                    'account_number': '0123456789',
                    'account_name': 'John Doe',
                    'bank_code': '058',
                    'bank_name': 'Guaranty Trust Bank'
                }
            },
            'message': 'Recipient created'
        }
        mock_post.return_value = mock_response
        
        result = self.service.create_transfer_recipient(
            account_number='0123456789',
            bank_code='058',
            account_name='John Doe',
            email='john@example.com'
        )
        
        self.assertTrue(result['success'])
        self.assertEqual(result['recipient_code'], 'RCP_test123')
        self.assertEqual(result['account_number'], '0123456789')
        self.assertEqual(result['account_name'], 'John Doe')
        self.assertEqual(result['bank_code'], '058')
        self.assertEqual(result['bank_name'], 'Guaranty Trust Bank')
        
        # Verify API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn('/transferrecipient', call_args[0][0])
        self.assertEqual(call_args[1]['json']['account_number'], '0123456789')
        self.assertEqual(call_args[1]['json']['bank_code'], '058')
    
    @patch('wallet.paystack_service.requests.post')
    def test_create_transfer_recipient_failure(self, mock_post):
        """Test transfer recipient creation failure"""
        # Mock failed response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': False,
            'message': 'Invalid bank code'
        }
        mock_post.return_value = mock_response
        
        result = self.service.create_transfer_recipient(
            account_number='0123456789',
            bank_code='999'  # Invalid bank code
        )
        
        self.assertFalse(result['success'])
        self.assertIsNone(result['recipient_code'])
        self.assertIn('Invalid bank code', result['message'])
    
    @patch('wallet.paystack_service.requests.post')
    def test_create_transfer_recipient_not_configured(self, mock_post):
        """Test transfer recipient creation when Paystack is not configured"""
        # Mock no secret key
        original_secret = self.service.secret_key
        self.service.secret_key = None
        
        result = self.service.create_transfer_recipient(
            account_number='0123456789',
            bank_code='058'
        )
        
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], 'Paystack not configured')
        
        # Restore secret key
        self.service.secret_key = original_secret
        mock_post.assert_not_called()
    
    @patch('wallet.paystack_service.requests.post')
    def test_initiate_transfer_success(self, mock_post):
        """Test successful transfer initiation"""
        # Mock successful response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': True,
            'data': {
                'transfer_code': 'TRF_test456',
                'reference': 'ref_test789',
                'amount': 500000,  # 5000.00 in kobo
                'status': 'pending'
            },
            'message': 'Transfer queued'
        }
        mock_post.return_value = mock_response
        
        result = self.service.initiate_transfer(
            amount=Decimal('5000.00'),
            recipient_code='RCP_test123',
            reason='Withdrawal request',
            reference='withdrawal_ref_001'
        )
        
        self.assertTrue(result['success'])
        self.assertEqual(result['transfer_code'], 'TRF_test456')
        self.assertEqual(result['reference'], 'ref_test789')
        self.assertEqual(result['amount'], Decimal('5000.00'))
        self.assertEqual(result['status'], 'pending')
        
        # Verify API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn('/transfer', call_args[0][0])
        self.assertEqual(call_args[1]['json']['amount'], 500000)  # In kobo
        self.assertEqual(call_args[1]['json']['recipient'], 'RCP_test123')
        self.assertEqual(call_args[1]['json']['reason'], 'Withdrawal request')
    
    @patch('wallet.paystack_service.requests.post')
    def test_initiate_transfer_failure(self, mock_post):
        """Test transfer initiation failure"""
        # Mock failed response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': False,
            'message': 'Insufficient balance'
        }
        mock_post.return_value = mock_response
        
        result = self.service.initiate_transfer(
            amount=Decimal('10000.00'),
            recipient_code='RCP_test123'
        )
        
        self.assertFalse(result['success'])
        self.assertIsNone(result['transfer_code'])
        self.assertIn('Insufficient balance', result['message'])
    
    @patch('wallet.paystack_service.requests.post')
    def test_initiate_transfer_not_configured(self, mock_post):
        """Test transfer initiation when Paystack is not configured"""
        # Mock no secret key
        original_secret = self.service.secret_key
        self.service.secret_key = None
        
        result = self.service.initiate_transfer(
            amount=Decimal('100.00'),
            recipient_code='RCP_test123'
        )
        
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], 'Paystack not configured')
        
        # Restore secret key
        self.service.secret_key = original_secret
        mock_post.assert_not_called()
    
    @patch('wallet.paystack_service.requests.get')
    def test_verify_transfer_success_by_code(self, mock_get):
        """Test successful transfer verification using transfer_code"""
        # Mock successful response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': True,
            'data': {
                'transfer_code': 'TRF_test456',
                'reference': 'ref_test789',
                'amount': 500000,  # 5000.00 in kobo
                'status': 'success',
                'recipient': {
                    'recipient_code': 'RCP_test123'
                }
            },
            'message': 'Transfer retrieved'
        }
        mock_get.return_value = mock_response
        
        result = self.service.verify_transfer(transfer_code='TRF_test456')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['amount'], Decimal('5000.00'))
        self.assertEqual(result['transfer_code'], 'TRF_test456')
        self.assertEqual(result['reference'], 'ref_test789')
        self.assertEqual(result['recipient_code'], 'RCP_test123')
        
        # Verify API call
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertIn('/transfer/TRF_test456', call_args[0][0])
    
    @patch('wallet.paystack_service.requests.get')
    def test_verify_transfer_success_by_reference(self, mock_get):
        """Test successful transfer verification using reference"""
        # Mock successful response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': True,
            'data': {
                'transfer_code': 'TRF_test456',
                'reference': 'ref_test789',
                'amount': 500000,
                'status': 'success',
                'recipient': 'RCP_test123'  # String format
            }
        }
        mock_get.return_value = mock_response
        
        result = self.service.verify_transfer(reference='ref_test789')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'success')
        
        # Verify API call used reference
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertIn('/transfer/ref_test789', call_args[0][0])
    
    @patch('wallet.paystack_service.requests.get')
    def test_verify_transfer_pending_status(self, mock_get):
        """Test transfer verification with pending status"""
        # Mock pending response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': True,
            'data': {
                'transfer_code': 'TRF_test456',
                'reference': 'ref_test789',
                'amount': 500000,
                'status': 'pending',
                'recipient': {
                    'recipient_code': 'RCP_test123'
                }
            }
        }
        mock_get.return_value = mock_response
        
        result = self.service.verify_transfer(transfer_code='TRF_test456')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'pending')
    
    @patch('wallet.paystack_service.requests.get')
    def test_verify_transfer_failed_status(self, mock_get):
        """Test transfer verification with failed status"""
        # Mock failed response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': True,
            'data': {
                'transfer_code': 'TRF_test456',
                'reference': 'ref_test789',
                'amount': 500000,
                'status': 'failed',
                'recipient': {
                    'recipient_code': 'RCP_test123'
                }
            }
        }
        mock_get.return_value = mock_response
        
        result = self.service.verify_transfer(transfer_code='TRF_test456')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'failed')
    
    @patch('wallet.paystack_service.requests.get')
    def test_verify_transfer_not_found(self, mock_get):
        """Test transfer verification when transfer is not found"""
        # Mock not found response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': False,
            'message': 'Transfer not found'
        }
        mock_get.return_value = mock_response
        
        result = self.service.verify_transfer(transfer_code='TRF_invalid')
        
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'pending')
        self.assertIn('Transfer not found', result['message'])
    
    def test_verify_transfer_no_identifier(self):
        """Test transfer verification without transfer_code or reference"""
        result = self.service.verify_transfer()
        
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'pending')
        self.assertIn('Either transfer_code or reference is required', result['message'])
    
    @patch('wallet.paystack_service.requests.get')
    def test_verify_transfer_not_configured(self, mock_get):
        """Test transfer verification when Paystack is not configured"""
        # Mock no secret key
        original_secret = self.service.secret_key
        self.service.secret_key = None
        
        result = self.service.verify_transfer(transfer_code='TRF_test456')
        
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(result['message'], 'Paystack not configured')
        
        # Restore secret key
        self.service.secret_key = original_secret
        mock_get.assert_not_called()
    
    @patch('wallet.paystack_service.requests.post')
    def test_create_transfer_recipient_exception_handling(self, mock_post):
        """Test exception handling in create_transfer_recipient"""
        # Mock exception
        mock_post.side_effect = Exception('Network error')
        
        result = self.service.create_transfer_recipient(
            account_number='0123456789',
            bank_code='058'
        )
        
        self.assertFalse(result['success'])
        self.assertIn('Error:', result['message'])
    
    @patch('wallet.paystack_service.requests.post')
    def test_initiate_transfer_exception_handling(self, mock_post):
        """Test exception handling in initiate_transfer"""
        # Mock exception
        mock_post.side_effect = Exception('Network error')
        
        result = self.service.initiate_transfer(
            amount=Decimal('100.00'),
            recipient_code='RCP_test123'
        )
        
        self.assertFalse(result['success'])
        self.assertIn('Error:', result['message'])
    
    @patch('wallet.paystack_service.requests.get')
    def test_verify_transfer_exception_handling(self, mock_get):
        """Test exception handling in verify_transfer"""
        # Mock exception
        mock_get.side_effect = Exception('Network error')
        
        result = self.service.verify_transfer(transfer_code='TRF_test456')
        
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'pending')
        self.assertIn('Verification error:', result['message'])
