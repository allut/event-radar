"""Static styles for HTML emails (digest, etc.)."""

DIGEST_CSS = """
body{margin:0;padding:0;background:#0d0d0d;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;color:#e8e2d5;}
.wrap{max-width:600px;margin:0 auto;padding:32px 20px;}
h1{font-size:13px;letter-spacing:3px;text-transform:uppercase;color:#8b7d6b;margin:0 0 4px 0;}
h2{font-size:22px;font-weight:400;color:#e8e2d5;margin:0 0 32px 0;}
.event{border-top:1px solid #2a2522;padding:20px 0;}
.event-title{font-size:18px;font-weight:600;color:#e8e2d5;margin:0 0 4px 0;text-decoration:none;}
.event-title:hover{color:#c9a96e;}
.event-meta{font-size:12px;color:#8b7d6b;margin:0 0 10px 0;}
.bullets{margin:0;padding:0 0 0 16px;color:#c4bdb5;font-size:14px;line-height:1.7;}
.price{font-size:12px;color:#8b7d6b;margin:4px 0 0 0;}
.footer{margin-top:40px;padding-top:20px;border-top:1px solid #2a2522;font-size:11px;color:#5a4f47;text-align:center;}
.footer a{color:#8b7d6b;}
"""
