@echo off
setlocal EnableExtensions
set "FOUND="
for /f "delims=" %%I in ('dir /b /ad /o-n "%USERPROFILE%\.vscode\extensions\jamied.sysml-v2-support-*" 2^>nul') do (
  if exist "%USERPROFILE%\.vscode\extensions\%%I\node_modules\sysml-v2-lsp\dist\server\mcpServer.js" (
    set "FOUND=%USERPROFILE%\.vscode\extensions\%%I\node_modules\sysml-v2-lsp\dist\server\mcpServer.js"
    goto :run
  )
)
for /f "delims=" %%I in ('dir /b /ad /o-n "%USERPROFILE%\.cursor\extensions\jamied.sysml-v2-support-*" 2^>nul') do (
  if exist "%USERPROFILE%\.cursor\extensions\%%I\node_modules\sysml-v2-lsp\dist\server\mcpServer.js" (
    set "FOUND=%USERPROFILE%\.cursor\extensions\%%I\node_modules\sysml-v2-lsp\dist\server\mcpServer.js"
    goto :run
  )
)
echo JamieD sysml-v2-support MCP server not found. Install JamieD.sysml-v2-support. 1>&2
exit /b 1
:run
node "%FOUND%" %*
