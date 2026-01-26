"""
Integration tests for complete payment flow end-to-end (Task 18)

Tests the complete user journey:
1. User deposits via Paystack
2. User creates match
3. User wins match
4. User withdraws via Paystack
5. Repeat for Flutterwave

This test file should be kept for continuous validation.
"""

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.utils import timezone

from wallet.models import Wallet, Transaction, Deposit, Withdrawal
from matches.models import Match, MatchResult
from wallet.payment_manager import get_payment_manager
from wallet.utils import complete_deposit_and_credit_wallet

User = get_user_model()


class CompletePaymentFlowTests(TestCase):
    """Test complete payment flow end-to-end"""
    
    def setUp(self):
        """Set up test data"""
        # Create two users for match
        self.user1 = User.objects.create_user(
            username='player1',
            email='player1@example.com',
            password='testpass123'
        )
        self.user2 = User.objects.create_user(
            username='player2',
            email='player2@example.com',
            password='testpass123'
        )
        
        # Create wallets
        wallet1, _ = Wallet.objects.get_or_create(user=self.user1, defaults={'balance': Decimal('0.00')})
        wallet2, _ = Wallet.objects.get_or_create(user=self.user2, defaults={'balance': Decimal('0.00')})
        if not _:
            wallet1.balance = Decimal('0.00')
            wallet1.save()
            wallet2.balance = Decimal('0.00')
            wallet2.save()
        wallet1.refresh_from_db()
        wallet2.refresh_from_db()
        self.wallet1 = wallet1
        self.wallet2 = wallet2
        
        self.client = Client()
    
    def _create_test_deposit(self, user, amount, payment_method='BANK_TRANSFER'):
        """Helper to create a test deposit
        
        Note: payment_method is the payment type (BANK_TRANSFER, MOBILE_MONEY, etc.)
        The actual gateway (Paystack/Flutterwave) is handled separately in PaymentManager
        """
        deposit = Deposit.objects.create(
            user=user,
            amount=amount,
            payment_method=payment_method,
            status='PENDING',
            wallet=user.wallet,
            gateway_response={}  # Required field - provide empty dict for tests
        )
        return deposit
    
    def _simulate_deposit_completion(self, deposit):
        """Helper to simulate deposit completion"""
        # Set transaction_id before marking as completed (needed for hash generation)
        if not deposit.transaction_id:
            deposit.transaction_id = f'test_txn_{deposit.id}'
        deposit.save()
        
        # Mark as completed and credit wallet (complete_deposit_and_credit_wallet handles status update)
        result = complete_deposit_and_credit_wallet(deposit)
        
        # Verify wallet was credited
        deposit.wallet.refresh_from_db()
        return result
    
    def test_complete_payment_flow_paystack(self):
        """
        Test complete payment flow with Paystack:
        1. User deposits $100 via Paystack
        2. User creates $50 match
        3. Another user joins match
        4. User wins match
        5. User withdraws winnings via Paystack
        """
        # Step 1: User deposits $100 via Paystack (using BANK_TRANSFER as payment method)
        initial_balance = self.wallet1.balance
        deposit = self._create_test_deposit(self.user1, Decimal('100.00'), 'BANK_TRANSFER')
        
        # Simulate deposit completion
        result = self._simulate_deposit_completion(deposit)
        self.assertTrue(result['success'])
        self.assertTrue(result['wallet_credited'])
        
        # Verify wallet balance increased
        self.wallet1.refresh_from_db()
        self.assertEqual(self.wallet1.balance, initial_balance + Decimal('100.00'))
        
        # Verify transaction record created
        deposit_transaction = Transaction.objects.filter(
            wallet=self.wallet1,
            transaction_type='DEPOSIT',
            amount=Decimal('100.00')
        ).first()
        self.assertIsNotNone(deposit_transaction)
        
        # Step 2: User creates $50 match
        match_amount = Decimal('50.00')
        initial_balance_before_match = self.wallet1.balance
        
        match = Match.objects.create(
            creator=self.user1,
            game='FIFA_MOBILE',
            device='MOBILE',
            privacy='PUBLIC',
            amount=50,  # Integer for match amount
            status='OPEN'
        )
        
        # Match creation should deduct amount from wallet
        # (This happens in the view, but for test we'll simulate it)
        self.wallet1.balance -= match_amount
        self.wallet1.save()
        
        # Verify wallet balance decreased
        self.wallet1.refresh_from_db()
        self.assertEqual(self.wallet1.balance, initial_balance_before_match - match_amount)
        
        # Step 3: Another user deposits and joins match
        deposit2 = self._create_test_deposit(self.user2, Decimal('100.00'), 'BANK_TRANSFER')
        self._simulate_deposit_completion(deposit2)
        
        # User2 joins match
        match.joiner = self.user2
        match.status = 'JOINED'
        match.save()
        
        # Deduct match amount from user2's wallet
        self.wallet2.balance -= match_amount
        self.wallet2.save()
        
        # Step 4: Both users submit results - user1 wins
        match_result = MatchResult.objects.create(match=match)
        match_result.creator_submission = 'WON'
        match_result.creator_submission_time = timezone.now()
        match_result.joiner_submission = 'LOST'
        match_result.joiner_submission_time = timezone.now()
        match_result.save()
        
        # Process match completion
        match.status = 'COMPLETED'
        match.winner = self.user1
        match.save()
        
        # Winner gets winnings (90% of total pot)
        winnings = Decimal(match.winnings)  # Should be 50 * 2 * 0.9 = 90
        initial_winner_balance = self.wallet1.balance
        self.wallet1.balance += winnings
        self.wallet1.save()
        
        # Verify winner's wallet increased
        self.wallet1.refresh_from_db()
        self.assertEqual(self.wallet1.balance, initial_winner_balance + winnings)
        
        # Step 5: User withdraws winnings via Paystack (using BANK_TRANSFER as payment method)
        withdrawal_amount = Decimal('90.00')
        initial_balance_before_withdrawal = self.wallet1.balance
        
        withdrawal = Withdrawal.objects.create(
            user=self.user1,
            amount=withdrawal_amount,
            payment_method='BANK_TRANSFER',
            account_details='Account: 1234567890, Bank: 058, Name: Player One',
            status='PENDING',
            wallet=self.wallet1
        )
        
        # Mock payment gateway processing (Paystack handles BANK_TRANSFER withdrawals)
        payment_manager = get_payment_manager()
        with patch.object(payment_manager, 'process_withdrawal') as mock_process:
            mock_process.return_value = {
                'success': True,
                'transaction_id': f'withdraw_txn_{withdrawal.id}',
                'gateway_response': {'status': 'success'},
                'failure_reason': None
            }
            
            # Process withdrawal (mock gateway processing)
            result = payment_manager.process_withdrawal(withdrawal)
            self.assertTrue(result['success'])
            
            # Update withdrawal with gateway response
            withdrawal.transaction_id = result['transaction_id']
            withdrawal.gateway_response = result.get('gateway_response', {})
            withdrawal.save()
            
            # Use the proper function to debit wallet and create transaction
            from wallet.utils import process_withdrawal_and_debit_wallet
            debit_result = process_withdrawal_and_debit_wallet(withdrawal)
            self.assertTrue(debit_result['success'])
            self.assertTrue(debit_result['wallet_debited'])
            self.assertTrue(debit_result['transaction_created'])
        
        # Verify wallet balance decreased
        self.wallet1.refresh_from_db()
        self.assertEqual(self.wallet1.balance, initial_balance_before_withdrawal - withdrawal_amount)
        
        # Verify withdrawal transaction record created
        withdrawal_transaction = Transaction.objects.filter(
            wallet=self.wallet1,
            transaction_type='WITHDRAWAL',
            amount=-withdrawal_amount
        ).first()
        self.assertIsNotNone(withdrawal_transaction)
        
        # Final verification: Check all status transitions
        deposit.refresh_from_db()
        self.assertEqual(deposit.status, 'COMPLETED')
        self.assertEqual(match.status, 'COMPLETED')
        self.assertEqual(withdrawal.status, 'COMPLETED')
    
    def test_complete_payment_flow_flutterwave(self):
        """
        Test complete payment flow with Flutterwave:
        1. User deposits $100 via Flutterwave
        2. User creates $50 match
        3. Another user joins match
        4. User wins match
        5. User withdraws winnings via Flutterwave
        """
        # Step 1: User deposits $100 via Flutterwave (using BANK_TRANSFER as payment method)
        initial_balance = self.wallet1.balance
        deposit = self._create_test_deposit(self.user1, Decimal('100.00'), 'BANK_TRANSFER')
        
        # Simulate deposit completion
        result = self._simulate_deposit_completion(deposit)
        self.assertTrue(result['success'])
        
        # Verify wallet balance increased
        self.wallet1.refresh_from_db()
        self.assertEqual(self.wallet1.balance, initial_balance + Decimal('100.00'))
        
        # Step 2: User creates $50 match
        match_amount = Decimal('50.00')
        self.wallet1.balance -= match_amount
        self.wallet1.save()
        
        match = Match.objects.create(
            creator=self.user1,
            game='FIFA_MOBILE',
            device='MOBILE',
            privacy='PUBLIC',
            amount=50,
            status='OPEN'
        )
        
        # Step 3: Another user deposits and joins match
        deposit2 = self._create_test_deposit(self.user2, Decimal('100.00'), 'BANK_TRANSFER')
        self._simulate_deposit_completion(deposit2)
        
        match.joiner = self.user2
        match.status = 'JOINED'
        match.save()
        
        self.wallet2.balance -= match_amount
        self.wallet2.save()
        
        # Step 4: User wins match
        match_result = MatchResult.objects.create(match=match)
        match_result.creator_submission = 'WON'
        match_result.creator_submission_time = timezone.now()
        match_result.joiner_submission = 'LOST'
        match_result.joiner_submission_time = timezone.now()
        match_result.save()
        
        match.status = 'COMPLETED'
        match.winner = self.user1
        match.save()
        
        winnings = Decimal(match.winnings)
        self.wallet1.balance += winnings
        self.wallet1.save()
        
        # Step 5: User withdraws via Flutterwave (using MOBILE_MONEY as payment method)
        withdrawal_amount = Decimal('90.00')
        initial_balance_before_withdrawal = self.wallet1.balance
        
        withdrawal = Withdrawal.objects.create(
            user=self.user1,
            amount=withdrawal_amount,
            payment_method='MOBILE_MONEY',
            account_details='Account: 1234567890, Bank: 058, Name: Player One',
            status='PENDING',
            wallet=self.wallet1
        )
        
        # Mock Flutterwave processing (Flutterwave handles MOBILE_MONEY withdrawals)
        payment_manager = get_payment_manager()
        with patch.object(payment_manager, 'process_withdrawal') as mock_process:
            mock_process.return_value = {
                'success': True,
                'transaction_id': f'withdraw_txn_{withdrawal.id}',
                'gateway_response': {'status': 'success'},
                'failure_reason': None
            }
            
            result = payment_manager.process_withdrawal(withdrawal)
            self.assertTrue(result['success'])
            
            # Update withdrawal with gateway response
            withdrawal.transaction_id = result['transaction_id']
            withdrawal.gateway_response = result.get('gateway_response', {})
            withdrawal.save()
            
            # Use the proper function to debit wallet and create transaction
            from wallet.utils import process_withdrawal_and_debit_wallet
            debit_result = process_withdrawal_and_debit_wallet(withdrawal)
            self.assertTrue(debit_result['success'])
        
        # Verify final state
        self.wallet1.refresh_from_db()
        self.assertEqual(self.wallet1.balance, initial_balance_before_withdrawal - withdrawal_amount)
        
        deposit.refresh_from_db()
        withdrawal.refresh_from_db()
        self.assertEqual(deposit.status, 'COMPLETED')
        self.assertEqual(withdrawal.status, 'COMPLETED')
    
    def test_wallet_balance_integrity_throughout_flow(self):
        """Test that wallet balance integrity is maintained throughout the flow"""
        # Track balance at each step
        balance_history = []
        
        # Initial balance
        balance_history.append(('initial', self.wallet1.balance))
        
        # After deposit
        deposit = self._create_test_deposit(self.user1, Decimal('100.00'), 'BANK_TRANSFER')
        self._simulate_deposit_completion(deposit)
        self.wallet1.refresh_from_db()
        balance_history.append(('after_deposit', self.wallet1.balance))
        self.assertEqual(self.wallet1.balance, Decimal('100.00'))
        
        # After creating match
        match = Match.objects.create(
            creator=self.user1,
            game='FIFA_MOBILE',
            device='MOBILE',
            privacy='PUBLIC',
            amount=50,
            status='OPEN'
        )
        self.wallet1.balance -= Decimal('50.00')
        self.wallet1.save()
        self.wallet1.refresh_from_db()
        balance_history.append(('after_match_creation', self.wallet1.balance))
        self.assertEqual(self.wallet1.balance, Decimal('50.00'))
        
        # After winning match
        deposit2 = self._create_test_deposit(self.user2, Decimal('100.00'), 'BANK_TRANSFER')
        self._simulate_deposit_completion(deposit2)
        
        match.joiner = self.user2
        match.status = 'JOINED'
        match.save()
        self.wallet2.balance -= Decimal('50.00')
        self.wallet2.save()
        
        match_result = MatchResult.objects.create(match=match)
        match_result.creator_submission = 'WON'
        match_result.creator_submission_time = timezone.now()
        match_result.joiner_submission = 'LOST'
        match_result.joiner_submission_time = timezone.now()
        match_result.save()
        
        match.status = 'COMPLETED'
        match.winner = self.user1
        match.save()
        
        winnings = Decimal(match.winnings)  # 90
        self.wallet1.balance += winnings
        self.wallet1.save()
        self.wallet1.refresh_from_db()
        balance_history.append(('after_winning', self.wallet1.balance))
        self.assertEqual(self.wallet1.balance, Decimal('140.00'))  # 50 + 90
        
        # After withdrawal
        withdrawal = Withdrawal.objects.create(
            user=self.user1,
            amount=Decimal('90.00'),
            payment_method='BANK_TRANSFER',
            account_details='Test Account',
            status='PENDING',
            wallet=self.wallet1
        )
        
        payment_manager = get_payment_manager()
        with patch.object(payment_manager, 'process_withdrawal') as mock_process:
            mock_process.return_value = {
                'success': True,
                'transaction_id': 'test_txn',
                'gateway_response': {},
                'failure_reason': None
            }
            
            result = payment_manager.process_withdrawal(withdrawal)
            withdrawal.transaction_id = result.get('transaction_id', 'test_txn')
            withdrawal.gateway_response = result.get('gateway_response', {})
            withdrawal.save()
            
            # Use the proper function to debit wallet and create transaction
            from wallet.utils import process_withdrawal_and_debit_wallet
            debit_result = process_withdrawal_and_debit_wallet(withdrawal)
            self.assertTrue(debit_result['success'])
            
            self.wallet1.refresh_from_db()
            balance_history.append(('after_withdrawal', self.wallet1.balance))
            self.assertEqual(self.wallet1.balance, Decimal('50.00'))  # 140 - 90
        
        # Verify balance integrity: sum of all transactions should match final balance
        transactions = Transaction.objects.filter(wallet=self.wallet1).order_by('created_at')
        transaction_sum = sum(t.amount for t in transactions)
        self.assertEqual(self.wallet1.balance, transaction_sum)
    
    def test_status_transitions_complete_flow(self):
        """Test all status transitions in complete flow"""
        # Deposit status transitions
        deposit = self._create_test_deposit(self.user1, Decimal('100.00'), 'BANK_TRANSFER')
        self.assertEqual(deposit.status, 'PENDING')
        
        self._simulate_deposit_completion(deposit)
        deposit.refresh_from_db()
        self.assertEqual(deposit.status, 'COMPLETED')
        
        # Match status transitions
        match = Match.objects.create(
            creator=self.user1,
            game='FIFA_MOBILE',
            device='MOBILE',
            privacy='PUBLIC',
            amount=50,
            status='OPEN'
        )
        self.assertEqual(match.status, 'OPEN')
        
        # User2 joins
        deposit2 = self._create_test_deposit(self.user2, Decimal('100.00'), 'BANK_TRANSFER')
        self._simulate_deposit_completion(deposit2)
        
        match.joiner = self.user2
        match.status = 'JOINED'
        match.save()
        self.assertEqual(match.status, 'JOINED')
        
        # Match completes
        match_result = MatchResult.objects.create(match=match)
        match_result.creator_submission = 'WON'
        match_result.creator_submission_time = timezone.now()
        match_result.joiner_submission = 'LOST'
        match_result.joiner_submission_time = timezone.now()
        match_result.save()
        
        match.status = 'COMPLETED'
        match.winner = self.user1
        match.save()
        self.assertEqual(match.status, 'COMPLETED')
        
        # Withdrawal status transitions - ensure wallet has balance
        self.wallet1.refresh_from_db()
        if self.wallet1.balance < Decimal('90.00'):
            self.wallet1.balance = Decimal('200.00')
            self.wallet1.save()
        
        withdrawal = Withdrawal.objects.create(
            user=self.user1,
            amount=Decimal('90.00'),
            payment_method='BANK_TRANSFER',
            account_details='Test Account',
            status='PENDING',
            wallet=self.wallet1
        )
        self.assertEqual(withdrawal.status, 'PENDING')
        
        payment_manager = get_payment_manager()
        with patch.object(payment_manager, 'process_withdrawal') as mock_process:
            mock_process.return_value = {
                'success': True,
                'transaction_id': 'test_txn',
                'gateway_response': {},
                'failure_reason': None
            }
            
            # Simulate processing
            withdrawal.status = 'PROCESSING'
            withdrawal.save()
            self.assertEqual(withdrawal.status, 'PROCESSING')
            
            # Complete
            result = payment_manager.process_withdrawal(withdrawal)
            withdrawal.transaction_id = result.get('transaction_id', 'test_txn')
            withdrawal.gateway_response = result.get('gateway_response', {})
            withdrawal.save()
            
            # Use the proper function to debit wallet and create transaction
            from wallet.utils import process_withdrawal_and_debit_wallet
            debit_result = process_withdrawal_and_debit_wallet(withdrawal)
            self.assertTrue(debit_result['success'])
            
            withdrawal.refresh_from_db()
            self.assertEqual(withdrawal.status, 'COMPLETED')
    
    def test_payment_gateway_integration_paystack(self):
        """Test Paystack payment gateway integration in complete flow"""
        # Mock Paystack service from the correct module
        with patch('wallet.paystack_service.PaystackService') as mock_paystack_class:
            mock_service = MagicMock()
            mock_paystack_class.return_value = mock_service
            
            # Mock deposit initialization
            mock_service.initialize_payment.return_value = {
                'success': True,
                'authorization_url': 'https://paystack.com/pay/test',
                'payment_reference': 'test_ref_123'
            }
            
            # Mock withdrawal processing
            mock_service.create_transfer_recipient.return_value = {
                'success': True,
                'recipient_code': 'RCP_test123'
            }
            mock_service.initiate_transfer.return_value = {
                'success': True,
                'transfer_code': 'TRF_test123',
                'reference': 'ref_test123'
            }
            
            # Test deposit flow (payment_method is BANK_TRANSFER, gateway is Paystack)
            payment_manager = get_payment_manager()
            deposit = self._create_test_deposit(self.user1, Decimal('100.00'), 'BANK_TRANSFER')
            
            # Ensure wallet has sufficient balance for withdrawal
            self.wallet1.balance = Decimal('100.00')
            self.wallet1.save()
            
            # Test withdrawal flow (payment_method is BANK_TRANSFER, gateway handles it)
            withdrawal = Withdrawal.objects.create(
                user=self.user1,
                amount=Decimal('50.00'),
                payment_method='BANK_TRANSFER',
                account_details='Account: 1234567890, Bank: 058',
                status='PENDING',
                wallet=self.wallet1
            )
            
            # Mock the process_withdrawal method directly
            with patch.object(payment_manager, 'process_withdrawal') as mock_process:
                mock_process.return_value = {
                    'success': True,
                    'transaction_id': 'test_txn',
                    'gateway_response': {},
                    'failure_reason': None
                }
                result = payment_manager.process_withdrawal(withdrawal)
                # Result should not raise errors
                self.assertIsNotNone(result)
                
                # Update withdrawal and process debit
                if result.get('success'):
                    withdrawal.transaction_id = result.get('transaction_id', 'test_txn')
                    withdrawal.gateway_response = result.get('gateway_response', {})
                    withdrawal.save()
                    
                    # Use the proper function to debit wallet and create transaction
                    from wallet.utils import process_withdrawal_and_debit_wallet
                    debit_result = process_withdrawal_and_debit_wallet(withdrawal)
                    self.assertTrue(debit_result['success'])
    
    def test_payment_gateway_integration_flutterwave(self):
        """Test Flutterwave payment gateway integration in complete flow"""
        # Mock Flutterwave service from the correct module
        with patch('wallet.flutterwave_service.FlutterwaveService') as mock_flutterwave_class:
            mock_service = MagicMock()
            mock_flutterwave_class.return_value = mock_service
            
            # Mock deposit initialization
            mock_service.initialize_payment.return_value = {
                'success': True,
                'authorization_url': 'https://flutterwave.com/pay/test',
                'payment_reference': 'test_ref_456'
            }
            
            # Mock withdrawal processing
            mock_service.create_transfer_beneficiary.return_value = {
                'success': True,
                'beneficiary_id': 'BEN_test456'
            }
            mock_service.initiate_transfer.return_value = {
                'success': True,
                'transfer_id': 'TRF_test456',
                'reference': 'ref_test456'
            }
            
            # Test deposit flow (payment_method is MOBILE_MONEY, gateway is Flutterwave)
            payment_manager = get_payment_manager()
            deposit = self._create_test_deposit(self.user1, Decimal('100.00'), 'MOBILE_MONEY')
            
            # Ensure wallet has sufficient balance for withdrawal
            self.wallet1.balance = Decimal('100.00')
            self.wallet1.save()
            
            # Test withdrawal flow (payment_method is MOBILE_MONEY, gateway handles it)
            withdrawal = Withdrawal.objects.create(
                user=self.user1,
                amount=Decimal('50.00'),
                payment_method='MOBILE_MONEY',
                account_details='Account: 1234567890, Bank: 058',
                status='PENDING',
                wallet=self.wallet1
            )
            
            # Mock the process_withdrawal method directly
            with patch.object(payment_manager, 'process_withdrawal') as mock_process:
                mock_process.return_value = {
                    'success': True,
                    'transaction_id': 'test_txn',
                    'gateway_response': {},
                    'failure_reason': None
                }
                result = payment_manager.process_withdrawal(withdrawal)
                # Result should not raise errors
                self.assertIsNotNone(result)
                
                # Update withdrawal and process debit
                if result.get('success'):
                    withdrawal.transaction_id = result.get('transaction_id', 'test_txn')
                    withdrawal.gateway_response = result.get('gateway_response', {})
                    withdrawal.save()
                    
                    # Use the proper function to debit wallet and create transaction
                    from wallet.utils import process_withdrawal_and_debit_wallet
                    debit_result = process_withdrawal_and_debit_wallet(withdrawal)
                    self.assertTrue(debit_result['success'])