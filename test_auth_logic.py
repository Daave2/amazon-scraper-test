
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

# Ensure we can import auth
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from auth import perform_login_and_otp

@pytest.mark.asyncio
async def test_login_success_account_picker():
    """Test login flow where it goes straight to account picker (skipping OTP)"""
    page = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.content = AsyncMock(return_value="<html></html>")
    
    logger = MagicMock()
    save_screenshot = AsyncMock()
    config = {'login_email': 'u', 'login_password': 'p', 'otp_secret_key': 'JBSWY3DPEHPK3PXP'}
    
    # Mock locator responses
    def get_locator_mock(selector):
        m = MagicMock() # Use MagicMock for the locator object, but methods are AsyncMock
        
        # Async methods on the locator
        m.is_visible = AsyncMock()
        m.fill = AsyncMock()
        m.click = AsyncMock()
        m.input_value = AsyncMock(return_value="p") # Default to successfully filled
        m.focus = AsyncMock()
        m.count = AsyncMock(return_value=1)
        
        # The .first property returns a locator too
        first_m = MagicMock()
        first_m.is_visible = AsyncMock()
        first_m.inner_text = AsyncMock(return_value="")
        m.first = first_m
        
        sel_str = str(selector)
        is_visible = False
        
        # Determine visibility based on selector
        if "Continue shopping" in sel_str:
            is_visible = False
        elif "captcha" in sel_str:
            is_visible = False
        elif "error" in sel_str:
            is_visible = False
        elif "otp" in sel_str:
            is_visible = False
        elif "Select an account" in sel_str:
            is_visible = True
        elif "ap_email" in sel_str:
            is_visible = True
        elif "ap_password" in sel_str: # New password ID
            is_visible = True
        elif "signInSubmit" in sel_str: # New button ID
            is_visible = True
        elif "missing-alert" in sel_str: # New validation alert
            is_visible = False
        elif "dashboard" in sel_str:
            is_visible = False
            
        m.is_visible.return_value = is_visible
        first_m.is_visible.return_value = is_visible
        
        return m

    page.locator = MagicMock(side_effect=get_locator_mock)
    page.get_by_label = MagicMock(return_value=get_locator_mock("generic_label"))
    page.get_by_role = MagicMock(return_value=get_locator_mock("generic_role"))
    
    # Mock expect
    mock_expect_obj = MagicMock()
    mock_expect_obj.to_be_visible = AsyncMock() 
    mock_expect = MagicMock(return_value=mock_expect_obj)
    
    with patch("auth.expect", new=mock_expect):
        result = await perform_login_and_otp(page, "http://login", config, 30000, False, logger, save_screenshot)
    
    # Assert success
    assert result is True
    
    # Verify we waited for the right things
    found_call = False
    for call_args in page.wait_for_selector.call_args_list:
        args, _ = call_args
        selector_str = args[0]
        if "otp" in selector_str:
            target_selectors = ["Select an account", "captcha", "error"]
            if all(s in selector_str for s in target_selectors):
                found_call = True
                break
    assert found_call, "wait_for_selector did not include all expected selectors"

@pytest.mark.asyncio
async def test_login_blocked_by_captcha():
    """Test login flow blocked by Captcha"""
    page = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.content = AsyncMock(return_value="<html>Captch</html>")

    logger = MagicMock()
    save_screenshot = AsyncMock()
    config = {'login_email': 'u', 'login_password': 'p'}
    
    def get_locator_mock(selector):
        m = MagicMock()
        m.is_visible = AsyncMock()
        m.fill = AsyncMock()
        m.click = AsyncMock()
        m.input_value = AsyncMock(return_value="p")
        m.focus = AsyncMock()
        m.count = AsyncMock(return_value=1)

        first_m = MagicMock()
        first_m.is_visible = AsyncMock()
        m.first = first_m
        
        sel_str = str(selector)
        is_visible = False
        
        if "captcha" in sel_str:
            is_visible = True
        elif "ap_password" in sel_str:
            is_visible = True
        
        m.is_visible.return_value = is_visible
        first_m.is_visible.return_value = is_visible
        return m

    page.locator = MagicMock(side_effect=get_locator_mock)
    page.get_by_label = MagicMock(return_value=get_locator_mock("generic_label"))
    page.get_by_role = MagicMock(return_value=get_locator_mock("generic_role"))
    
    # Mock expect
    mock_expect_obj = MagicMock()
    mock_expect_obj.to_be_visible = AsyncMock() 
    mock_expect = MagicMock(return_value=mock_expect_obj)
    
    with patch("auth.expect", new=mock_expect):
        result = await perform_login_and_otp(page, "http://login", config, 30000, False, logger, save_screenshot)
    
    assert result is False
    logger.critical.assert_called_with("Login blocked by CAPTCHA.")

@pytest.mark.asyncio
async def test_retry_on_empty_password_field():
    """Test that we retry filling the password if input_value returns empty"""
    page = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    
    logger = MagicMock()
    save_screenshot = AsyncMock()
    config = {'login_email': 'u', 'login_password': 'p'}
    
    # Mock logic: first call to input_value is empty, second is filled
    input_value_responses = iter(["", "p"])
    
    def get_locator_mock(selector):
        m = MagicMock()
        m.is_visible = AsyncMock()
        m.fill = AsyncMock()
        m.click = AsyncMock()
        m.focus = AsyncMock()
        m.count = AsyncMock(return_value=1)
        
        # Determine visibility
        sel_str = str(selector)
        if "ap_password" in sel_str:
            m.is_visible.return_value = True
            
            # Special handling for input_value on password field
            async def side_effect_input():
                try:
                    return next(input_value_responses)
                except StopIteration:
                    return "p"
            m.input_value = AsyncMock(side_effect=side_effect_input)
            
        elif "signInSubmit" in sel_str:
            m.is_visible.return_value = True
            m.input_value = AsyncMock(return_value="")
        else:
             m.is_visible.return_value = False
             m.input_value = AsyncMock(return_value="")

        first_m = MagicMock()
        first_m.is_visible = AsyncMock(return_value=m.is_visible.return_value)
        m.first = first_m
        
        return m

    page.locator = MagicMock(side_effect=get_locator_mock)
    page.get_by_label = MagicMock(return_value=get_locator_mock("generic_label"))
    page.get_by_role = MagicMock(return_value=get_locator_mock("generic_role"))
    
    mock_expect = MagicMock(return_value=MagicMock(to_be_visible=AsyncMock()))
    
    with patch("auth.expect", new=mock_expect):
        # We expect a success eventually, but we want to verify the specific retry log
        await perform_login_and_otp(page, "http://login", config, 30000, False, logger, save_screenshot)
    
    # Assert we warned about the empty field
    logger.warning.assert_any_call("Password field found empty after fill. Retrying with explicit focus...")

