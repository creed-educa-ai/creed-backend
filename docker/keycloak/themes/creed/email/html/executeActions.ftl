<#--
  O e-mail do convite e da redefinição de senha: o back manda o mesmo nos dois casos
  (send_update_password_email), sempre com a ação UPDATE_PASSWORD. Por isso o texto
  fala em "definir a senha" e serve aos dois.

  Se um dia outra ação vier junto, o e-mail não mente: troca para o texto genérico
  de "atualizar a conta", com a lista das ações, como o do `base`.

  O botão é o "bulletproof" de e-mail: uma célula de tabela pintada com o link
  dentro, que o Outlook também desenha.
-->
<#outputformat "plainText">
<#assign requiredActionsText><#if requiredActions??><#list requiredActions><#items as reqActionItem>${msg("requiredAction.${reqActionItem}")}<#sep>, </#sep></#items></#list></#if></#assign>
</#outputformat>
<#assign soSenha = requiredActions?? && requiredActions?size == 1 && requiredActions[0] == "UPDATE_PASSWORD">

<#import "template.ftl" as layout>
<@layout.emailLayout>
    <h1 style="margin:0 0 8px; font-size:24px; line-height:32px; font-weight:700; color:#532B88;">
        ${msg(soSenha?then("creedEmailSenhaTitulo", "creedEmailAcoesTitulo"))}
    </h1>
    <p style="margin:0 0 28px; font-size:15px; line-height:22px; color:#565460;">
        <#if soSenha>
            ${msg("creedEmailSenhaTexto", layout.nomeSemLink(realmName))}
        <#else>
            ${msg("creedEmailAcoesTexto", layout.nomeSemLink(realmName), requiredActionsText)}
        </#if>
    </p>

    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
            <td align="center" bgcolor="#532B88" style="background-color:#532B88; border-radius:10px;">
                <a href="${link}" target="_blank" style="display:block; padding:12px 20px; border-radius:10px; font-family:'Atkinson Hyperlegible', Arial, Helvetica, sans-serif; font-size:15px; line-height:20px; font-weight:700; color:#FFFFFF; text-decoration:none;">
                    ${msg(soSenha?then("creedEmailSenhaBotao", "creedEmailAcoesBotao"))}
                </a>
            </td>
        </tr>
    </table>
    <p style="margin:14px 0 0; font-size:13px; line-height:20px; color:#565460; text-align:center;">
        ${msg("creedEmailValidade", linkExpirationFormatter(linkExpiration))}
    </p>

    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:28px 0 20px;">
        <tr><td style="border-top:1px solid #DED7EC; font-size:0; line-height:0;">&nbsp;</td></tr>
    </table>

    <p style="margin:0 0 6px; font-size:13px; line-height:20px; color:#565460;">
        ${msg("creedEmailLinkManual")}
    </p>
    <#-- O link do Keycloak é longo (leva um token inteiro): pequeno e na cor de
         apoio, para não pesar mais que o botão. -->
    <p style="margin:0; font-size:11px; line-height:16px; word-break:break-all;">
        <a href="${link}" target="_blank" style="color:#565460; text-decoration:underline;">${link}</a>
    </p>
    <p style="margin:20px 0 0; font-size:13px; line-height:20px; color:#565460;">
        ${msg("creedEmailIgnorar")}
    </p>
</@layout.emailLayout>
