@echo off
REM Usage: sign.bat CERTIFICATE_SHA1_THUMBPRINT
REM Requires a trusted certificate in the current user certificate store.
if "%~1"=="" (
    echo Usage: sign.bat CERTIFICATE_SHA1_THUMBPRINT
    exit /b 1
)
py -3.14 "%~dp0build.py" --sign --certificate-thumbprint "%~1"
exit /b %errorlevel%
