<#--
  Moldura de todos os e-mails em HTML do tema. Cada e-mail do `base` chama
  <@layout.emailLayout>, então os que não foram reescritos aqui também ganham a
  moldura.

  E-mail não é navegador: o Gmail descarta <style> em parte dos casos, o Outlook
  não sabe flexbox nem border-radius, e ninguém lê CSS de outro arquivo. Por isso a
  página é de tabelas, com todo o estilo inline e a cor também no `bgcolor`. As
  cores são os tokens do front (src/index.css), em hex: o e-mail não entende oklch.
  A fonte cai na Arial onde a Atkinson Hyperlegible não existe, que é quase sempre.

  Desenho: a faixa roxa com o logo no topo, como o painel da marca do AuthLayout no
  celular, e o conteúdo num cartão branco embaixo.
-->
<#macro emailLayout>
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <#-- Sem isto, o modo escuro de alguns clientes inverte o roxo e o branco. -->
    <meta name="color-scheme" content="light">
    <meta name="supported-color-schemes" content="light">
    <title>${realmName}</title>
</head>
<body style="margin:0; padding:0; background-color:#F3EEFB;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#F3EEFB" style="background-color:#F3EEFB;">
    <tr>
        <td align="center" style="padding:32px 16px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;">
                <#-- Faixa da marca. O degradê do bg-brand vale onde o cliente
                     entende; nos outros, fica o roxo principal do bgcolor. Sem a
                     imagem (bloqueada por padrão em alguns clientes), aparece o
                     texto alternativo em branco. -->
                <tr>
                    <td align="center" bgcolor="#532B88" style="background-color:#532B88; background-image:linear-gradient(135deg, #7C50B0, #532B88); border-radius:24px 24px 0 0; padding:28px 24px;">
                        <img src="${url.resourcesUrl}/img/logo.png" width="169" height="40" alt="CREED.ai" style="display:block; width:169px; height:40px; border:0; outline:none; text-decoration:none; color:#FFFFFF; font-family:'Atkinson Hyperlegible', Arial, Helvetica, sans-serif; font-size:24px; font-weight:700;">
                    </td>
                </tr>
                <tr>
                    <td bgcolor="#FFFFFF" style="background-color:#FFFFFF; border-radius:0 0 24px 24px; padding:32px 32px 36px; font-family:'Atkinson Hyperlegible', Arial, Helvetica, sans-serif; font-size:15px; line-height:22px; color:#2A2830;">
                        <#nested>
                    </td>
                </tr>
                <tr>
                    <td align="center" style="padding:20px 16px 0; font-family:'Atkinson Hyperlegible', Arial, Helvetica, sans-serif; font-size:12px; line-height:18px; color:#565460;">
                        ${msg("creedEmailRodape", nomeSemLink(realmName))}
                    </td>
                </tr>
            </table>
        </td>
    </tr>
</table>
</body>
</html>
</#macro>

<#-- "CREED.ai" é um domínio válido: solto no texto, o Gmail, o Outlook e o iPhone o
     transformam em link para um site que não é o nosso. Um espaço de largura zero
     depois do ponto desfaz o link sem mudar o que a pessoa lê. -->
<#function nomeSemLink nome>
    <#return nome?replace(".", ".\x200B")>
</#function>
